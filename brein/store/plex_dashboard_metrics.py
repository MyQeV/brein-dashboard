"""Dashboard metrics from pre-computed daily snapshot tables (Plex).

Playback facts come from ``plex_playback_sessions`` (sessions finalized from live
``/status/sessions`` polling only). Metrics are not full Plex server history.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brein import config as brein_config
from brein.db import get_session_factory
from brein.store import plex_playback_sessions as store_plex_playback
from brein.store.metrics_helpers import (
    _UTC_TEXT_WINDOW,
    _snapshot_rebuild_since,
    _snapshot_since_params,
    _user_instance_filter as _shared_user_instance_filter,
    _utc_window_params,
)

log = logging.getLogger(__name__)

_rebuild_lock = asyncio.Lock()
# The finalised-session marker only covers this process, so the first
# rebuild after boot — and the one after a failed pass — is a full one.
_snapshot_full_pending = True


def _item_type_case(raw: str) -> str:
    """Normalise a raw Plex type expression to the snapshot's item_type words.

    The snapshot writes 'Movie'/'Episode'/'LiveTV'/'Audio'/'Other'; the
    user-filtered most-watched path used to return MAX(i.type) — 'movie' —
    so the same tile changed vocabulary depending on the filter.
    """
    return f"""CASE LOWER(TRIM(COALESCE({raw}, '')))
                        WHEN 'movie' THEN 'Movie'
                        WHEN 'episode' THEN 'Episode'
                        WHEN 'livetvchannel' THEN 'LiveTV'
                        WHEN 'program' THEN 'LiveTV'
                        WHEN 'track' THEN 'Audio'
                        WHEN 'album' THEN 'Audio'
                        ELSE 'Other'
                    END"""


def _local_date_expr(col: str, tz_param: str = "tz") -> str:
    """Return a SQL expression that converts a UTC ISO timestamp column to a local date string.

    Returns a text value in YYYY-MM-DD format so it can be compared directly with
    Python string date parameters (asyncpg requires date objects for ::date comparisons).
    The caller must include {tz_param} in their query params dict.
    """
    return f"to_char((LEFT({col}, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :{tz_param}), 'YYYY-MM-DD')"


def _instance_filter(
    instance_id: int | list[int] | None, column: str = "instance_id"
) -> tuple[str, dict[str, Any]]:
    """Return (WHERE fragment, params) for instance filter. Integer IDs formatted inline (safe)."""
    if instance_id is None:
        return "", {}
    if isinstance(instance_id, list):
        if not instance_id:
            return "", {}
        ids_str = ",".join(str(int(i)) for i in instance_id)
        return f" AND {column} IN ({ids_str})", {}
    return f" AND {column} = :iid", {"iid": int(instance_id)}


def _user_instance_filter(
    user_keys: list[str] | None,
    instance_col: str = "s.instance_id",
    user_col: str = "CAST(s.account_id AS TEXT)",
) -> tuple[str, dict[str, Any]]:
    """Delegate to the shared helper; this module used to hold a copy of it.

    Three copies meant three places to fix, and the copies missed the guards
    the shared one grew: a malformed instance prefix raised ValueError (a 500),
    and a filter whose every key was unusable returned an empty fragment, which
    drops the filter and answers for every user instead of none.
    """
    return _shared_user_instance_filter(user_keys, instance_col, user_col)


def _date_range_where(
    start_date: str, end_date: str, column: str = "stat_date"
) -> tuple[str, dict[str, str]]:
    """Return (AND fragment, params) for date-range filter."""
    return (
        f" AND {column} >= :start_date AND {column} <= :end_date",
        {"start_date": start_date, "end_date": end_date},
    )


async def rebuild_snapshots(
    instance_id: int | None = None, since_date: str | None = None
) -> None:
    """Re-populate the three snapshot tables from sessions + items + users.

    With ``since_date`` (a local YYYY-MM-DD stat_date) only that day and later
    are deleted and re-aggregated; without it every row is. The three tables
    share one bound and one transaction, so they never disagree with each
    other. Serialized via _rebuild_lock so concurrent callers (now-playing
    poller + scheduled task) don't race on DELETE/INSERT and trip a
    unique-violation.
    """
    async with _rebuild_lock, get_session_factory()() as session:
        tz = brein_config.TIMEZONE
        ld = _local_date_expr("s.start_time", "tz")

        inst_filter = ""
        inst_params: dict[str, Any] = {}
        del_where: list[str] = []
        if instance_id is not None:
            inst_filter = " AND s.instance_id = :instance_id"
            inst_params = {"instance_id": instance_id}
            del_where.append("instance_id = :instance_id")

        # The raw-text prefilter lets the start_time index prune the scan; the
        # local-date predicate decides, and matches the DELETE's bound exactly.
        since_filter = ""
        since_params: dict[str, Any] = {}
        if since_date:
            since_filter = f" AND s.start_time >= :since_lo AND {ld} >= :since_date"
            since_params = _snapshot_since_params(since_date)
            del_where.append("stat_date >= :since_date")

        inst_del_filter = (" WHERE " + " AND ".join(del_where)) if del_where else ""
        inst_del_params: dict[str, Any] = {**inst_params}
        if since_date:
            inst_del_params["since_date"] = since_date
        sel_params: dict[str, Any] = {"tz": tz, **inst_params, **since_params}

        # --- plex_metrics_snapshot (daily totals) ---
        await session.execute(
            text("DELETE FROM plex_metrics_snapshot" + inst_del_filter),
            inst_del_params,
        )
        await session.execute(
            text(
                f"""
                INSERT INTO plex_metrics_snapshot
                    (stat_date, instance_id, total_plays, total_watch_time_seconds,
                     total_movies, total_episodes, total_live_tv)
                SELECT
                    {ld} AS stat_date,
                    s.instance_id,
                    COUNT(*) AS total_plays,
                    COALESCE(SUM(s.watched_seconds), 0) AS total_watch_time_seconds,
                    SUM(CASE WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('movie') THEN 1 ELSE 0 END) AS total_movies,
                    SUM(CASE WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('episode') THEN 1 ELSE 0 END) AS total_episodes,
                    SUM(CASE WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('livetvchannel', 'program') THEN 1 ELSE 0 END) AS total_live_tv
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id AND i.item_id = s.rating_key
                WHERE 1=1 {inst_filter}{since_filter}
                GROUP BY {ld}, s.instance_id
                """
            ),
            sel_params,
        )

        # --- plex_metrics_snapshot_user (daily per-user) ---
        await session.execute(
            text("DELETE FROM plex_metrics_snapshot_user" + inst_del_filter),
            inst_del_params,
        )
        await session.execute(
            text(
                f"""
                INSERT INTO plex_metrics_snapshot_user
                    (stat_date, instance_id, user_id, user_name, plays, watch_time_seconds)
                SELECT
                    {ld} AS stat_date,
                    s.instance_id,
                    CAST(s.account_id AS TEXT) AS user_id,
                    MAX(COALESCE(u.title, u.username, s.account_title, '')) AS user_name,
                    COUNT(*) AS plays,
                    COALESCE(SUM(s.watched_seconds), 0) AS watch_time_seconds
                FROM plex_playback_sessions s
                LEFT JOIN plex_users u
                    ON u.instance_id = s.instance_id
                   AND u.user_id = s.account_id
                   AND u.is_deleted = 0
                -- A live poll that saw no account id finalises the session
                -- with a NULL one, and user_id is NOT NULL in the snapshot,
                -- so a single such row failed the whole rebuild on every run.
                -- Emby and Jellyfin exclude the same case when building
                -- sessions; Plex never did.
                WHERE s.account_id IS NOT NULL {inst_filter}{since_filter}
                GROUP BY {ld}, s.instance_id, s.account_id
                """
            ),
            sel_params,
        )

        # --- plex_metrics_snapshot_item (daily per-item, denormalized) ---
        await session.execute(
            text("DELETE FROM plex_metrics_snapshot_item" + inst_del_filter),
            inst_del_params,
        )
        await session.execute(
            text(
                f"""
                INSERT INTO plex_metrics_snapshot_item
                    (stat_date, instance_id, item_id, item_name, item_type,
                     series_id, series_name, display_label, plays)
                SELECT
                    {ld} AS stat_date,
                    s.instance_id,
                    s.rating_key AS item_id,
                    i.name,
                    {_item_type_case("i.type, MAX(s.item_type)")},
                    i.series_id,
                    series_item.name,
                    CASE
                        WHEN LOWER(TRIM(COALESCE(i.type, MAX(s.item_type), ''))) IN ('episode')
                             AND series_item.name IS NOT NULL
                             AND series_item.name != ''
                        THEN series_item.name || ' \u2013 ' || COALESCE(i.name, MAX(s.title), s.rating_key)
                        ELSE COALESCE(i.name, MAX(s.title), s.rating_key)
                    END,
                    COUNT(*) AS plays
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                LEFT JOIN plex_items series_item
                    ON series_item.instance_id = i.instance_id
                   AND series_item.item_id = i.series_id
                -- The item columns are functionally dependent on the
                -- joined rating_key, so grouping on them is safe. s.item_type
                -- and s.title are not — they belong to the session, and two
                -- plays of one item whose stored titles differ (renamed
                -- metadata, or a poll that omitted the field) produced two
                -- rows for a primary key of (stat_date, instance_id,
                -- item_id): a unique violation that failed every Plex rebuild
                -- until those rows aged out. Aggregated above instead.
                WHERE s.rating_key IS NOT NULL {inst_filter}{since_filter}
                GROUP BY {ld}, s.instance_id, s.rating_key,
                         i.name, i.type, i.series_id, series_item.name
                """
            ),
            sel_params,
        )

        await session.commit()
        log.info(
            "Plex dashboard snapshots rebuilt%s%s",
            f" for instance_id={instance_id}" if instance_id is not None else "",
            f" since {since_date}" if since_date else "",
        )


async def refresh_snapshots() -> None:
    """Rebuild only what the sessions finalised since the last call can have changed.

    Nothing finalised means nothing to do. The periodic caller used to run
    the full rebuild every pass, re-aggregating every session ever stored.
    """
    global _snapshot_full_pending
    changed_at = store_plex_playback.take_snapshot_since()
    since_date: str | None = None
    if not _snapshot_full_pending:
        if changed_at is None:
            return
        since_date = _snapshot_rebuild_since(changed_at)
    _snapshot_full_pending = False
    try:
        await rebuild_snapshots(since_date=since_date)
    except Exception:
        _snapshot_full_pending = True
        raise


# ---------------------------------------------------------------------------
# Read helpers (all query snapshot tables, accept a shared AsyncSession)
# ---------------------------------------------------------------------------


async def _get_snapshot_totals(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> dict[str, int]:
    """The scalar tiles that come straight off a snapshot table, in one query.

    Without a user filter that is plays, watch time, episodes and live TV
    from plex_metrics_snapshot; with one, plays and watch time from
    plex_metrics_snapshot_user (episodes and live TV then need the sessions —
    see the per-tile helpers). One round trip instead of four on a session
    that cannot run them concurrently anyway.
    """
    dr, dr_p = _date_range_where(start_date, end_date)
    inst_w, inst_p = _instance_filter(instance_id)
    if user_ids:
        usr_w, usr_p = _user_instance_filter(
            user_ids, "instance_id", "CAST(user_id AS TEXT)"
        )
        row = (
            await session.execute(
                text(
                    f"SELECT COALESCE(SUM(plays), 0), COALESCE(SUM(watch_time_seconds), 0)"
                    f" FROM plex_metrics_snapshot_user WHERE 1=1{dr}{inst_w}{usr_w}"
                ),
                {**dr_p, **inst_p, **usr_p},
            )
        ).fetchone()
        return {
            "total_plays": int(row[0]) if row else 0,
            "total_watch_time_seconds": int(row[1]) if row else 0,
        }
    row = (
        await session.execute(
            text(
                f"SELECT COALESCE(SUM(total_plays), 0),"
                f" COALESCE(SUM(total_watch_time_seconds), 0),"
                f" COALESCE(SUM(total_episodes), 0), COALESCE(SUM(total_live_tv), 0)"
                f" FROM plex_metrics_snapshot WHERE 1=1{dr}{inst_w}"
            ),
            {**dr_p, **inst_p},
        )
    ).fetchone()
    return {
        "total_plays": int(row[0]) if row else 0,
        "total_watch_time_seconds": int(row[1]) if row else 0,
        "total_watched_episodes": int(row[2]) if row else 0,
        "total_watched_live_tv": int(row[3]) if row else 0,
    }


async def _get_total_watched_movies(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> int:
    """Return count of distinct movies watched (by item_id) in the date range."""
    if user_ids:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        result = await session.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT (s.instance_id, s.rating_key))
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('movie')
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                """
            ),
            params,
        )
    else:
        dr, dr_p = _date_range_where(start_date, end_date)
        inst_w, inst_p = _instance_filter(instance_id)
        params = {**dr_p, **inst_p}
        result = await session.execute(
            text(
                f"SELECT COUNT(DISTINCT (instance_id, item_id))"
                f" FROM plex_metrics_snapshot_item"
                f" WHERE item_type = 'Movie'{dr}{inst_w}"
            ),
            params,
        )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def _get_total_watched_episodes(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> int:
    if user_ids:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        result = await session.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('episode')
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                """
            ),
            params,
        )
    else:
        dr, dr_p = _date_range_where(start_date, end_date)
        inst_w, inst_p = _instance_filter(instance_id)
        params = {**dr_p, **inst_p}
        result = await session.execute(
            text(
                f"SELECT COALESCE(SUM(total_episodes), 0)"
                f" FROM plex_metrics_snapshot WHERE 1=1{dr}{inst_w}"
            ),
            params,
        )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def _get_total_watched_series(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> int:
    if user_ids:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        result = await session.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT (s.instance_id, i.series_id))
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('episode')
                  AND i.series_id IS NOT NULL
                  AND i.series_id != ''
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                """
            ),
            params,
        )
    else:
        inst_w, inst_p = _instance_filter(instance_id)
        dr, dr_p = _date_range_where(start_date, end_date)
        params = {**dr_p, **inst_p}
        result = await session.execute(
            text(
                f"SELECT COUNT(DISTINCT (instance_id, series_id)) FROM plex_metrics_snapshot_item"
                f" WHERE item_type = 'Episode' AND series_id IS NOT NULL AND series_id != ''{dr}{inst_w}"
            ),
            params,
        )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def _get_total_watched_live_tv(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> int:
    if user_ids:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        result = await session.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('livetvchannel', 'program')
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                """
            ),
            params,
        )
    else:
        dr, dr_p = _date_range_where(start_date, end_date)
        inst_w, inst_p = _instance_filter(instance_id)
        params = {**dr_p, **inst_p}
        result = await session.execute(
            text(
                f"SELECT COALESCE(SUM(total_live_tv), 0)"
                f" FROM plex_metrics_snapshot WHERE 1=1{dr}{inst_w}"
            ),
            params,
        )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def _get_plays_per_user(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    dr, dr_p = _date_range_where(start_date, end_date)
    inst_w, inst_p = _instance_filter(instance_id)
    usr_w, usr_p = _user_instance_filter(
        user_ids, "instance_id", "CAST(user_id AS TEXT)"
    )
    params = {**dr_p, **inst_p, **usr_p}
    result = await session.execute(
        text(
            f"""
            SELECT instance_id, user_id, MAX(user_name) AS user_name, SUM(plays) AS plays
            FROM plex_metrics_snapshot_user
            WHERE 1=1{dr}{inst_w}{usr_w}
            GROUP BY instance_id, user_id
            ORDER BY plays DESC
            """
        ),
        params,
    )
    out: list[dict[str, Any]] = []
    for r in result.mappings().fetchall():
        iid = int(r["instance_id"]) if r["instance_id"] is not None else 0
        uid_str = str(r["user_id"]).strip() if r["user_id"] is not None else ""
        name = (r["user_name"] or "").strip()
        display_name = (
            name
            if name and name != uid_str
            else (f"User {uid_str}" if uid_str else "Unknown")
        )
        out.append(
            {
                "instance_id": iid,
                "user_id": uid_str,
                "user_name": name or None,
                "display_name": display_name,
                "plays": int(r["plays"]),
            }
        )
    return out


async def _get_watch_time_per_user(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    dr, dr_p = _date_range_where(start_date, end_date)
    inst_w, inst_p = _instance_filter(instance_id)
    usr_w, usr_p = _user_instance_filter(
        user_ids, "instance_id", "CAST(user_id AS TEXT)"
    )
    params = {**dr_p, **inst_p, **usr_p}
    result = await session.execute(
        text(
            f"""
            SELECT s.instance_id, s.user_id, MAX(s.user_name) AS user_name,
                   SUM(s.watch_time_seconds) AS total_seconds,
                   MAX(ai.label) AS instance_label
            FROM plex_metrics_snapshot_user s
            LEFT JOIN app_instances ai ON ai.id = s.instance_id
            WHERE 1=1{dr}{inst_w}{usr_w}
            GROUP BY s.instance_id, s.user_id
            ORDER BY total_seconds DESC
            """
        ),
        params,
    )
    out: list[dict[str, Any]] = []
    for r in result.mappings().fetchall():
        iid = int(r["instance_id"]) if r["instance_id"] is not None else 0
        uid_str = str(r["user_id"]).strip() if r["user_id"] is not None else ""
        name = (r["user_name"] or "").strip()
        display_name = (
            name
            if name and name != uid_str
            else (f"User {uid_str}" if uid_str else "Unknown")
        )
        out.append(
            {
                "instance_id": iid,
                "user_id": uid_str,
                "user_name": name or None,
                "display_name": display_name,
                "total_seconds": int(r["total_seconds"] or 0),
                "instance_label": r["instance_label"] or "",
            }
        )
    return out


async def _get_most_watched_items(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    limit: int = 20,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    if user_ids:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "limit": limit,
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        result = await session.execute(
            text(
                f"""
                SELECT
                    s.instance_id,
                    s.rating_key AS item_id,
                    MAX(i.name) AS item_name,
                    {_item_type_case("MAX(i.type), MAX(s.item_type)")} AS item_type,
                    CASE
                        WHEN LOWER(MAX(COALESCE(i.type, s.item_type, ''))) IN ('episode')
                             AND MAX(si.name) IS NOT NULL
                             AND MAX(si.name) != ''
                        THEN MAX(si.name) || ' \u2013 ' || COALESCE(MAX(i.name), s.rating_key)
                        ELSE COALESCE(MAX(i.name), s.rating_key)
                    END AS display_label,
                    COUNT(*) AS plays
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                LEFT JOIN plex_items si
                    ON si.instance_id = i.instance_id
                   AND si.item_id = i.series_id
                WHERE (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                GROUP BY s.instance_id, s.rating_key
                ORDER BY plays DESC
                LIMIT :limit
                """
            ),
            params,
        )
    else:
        dr, dr_p = _date_range_where(start_date, end_date)
        inst_w, inst_p = _instance_filter(instance_id)
        params = {**dr_p, **inst_p, "limit": limit}
        result = await session.execute(
            text(
                f"""
                SELECT instance_id, item_id,
                       MAX(item_name) AS item_name,
                       MAX(item_type) AS item_type,
                       MAX(display_label) AS display_label,
                       SUM(plays) AS plays
                FROM plex_metrics_snapshot_item
                WHERE 1=1{dr}{inst_w}
                GROUP BY instance_id, item_id
                ORDER BY plays DESC
                LIMIT :limit
                """
            ),
            params,
        )
    out: list[dict[str, Any]] = []
    for r in result.mappings().fetchall():
        out.append(
            {
                "instance_id": r["instance_id"],
                "item_id": r["item_id"],
                "plays": int(r["plays"]),
                "name": r["item_name"] or r["item_id"] or "Unknown",
                "type": r["item_type"] or "",
                "display_label": (
                    r["display_label"] or r["item_name"] or r["item_id"] or "Unknown"
                ),
            }
        )
    return out


async def _get_active_users_count(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> int:
    """Return count of distinct users with any play in the date range."""
    dr, dr_p = _date_range_where(start_date, end_date)
    inst_w, inst_p = _instance_filter(instance_id)
    usr_w, usr_p = _user_instance_filter(
        user_ids, "instance_id", "CAST(user_id AS TEXT)"
    )
    params = {**dr_p, **inst_p, **usr_p}
    result = await session.execute(
        text(
            # Scoped by instance like the Emby and Jellyfin counts: Plex
            # account ids are global, so one account active on two servers is
            # two rows in plays_per_user but was one user here.
            f"SELECT COUNT(DISTINCT (instance_id, user_id))"
            f" FROM plex_metrics_snapshot_user WHERE 1=1{dr}{inst_w}{usr_w}"
        ),
        params,
    )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def _get_streaming_by_hour(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return total watch time seconds grouped by hour-of-day (0-23)."""
    inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
    usr_w, usr_p = _user_instance_filter(
        user_ids, "instance_id", "CAST(account_id AS TEXT)"
    )
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        **_utc_window_params(start_date, end_date),
        "tz": brein_config.TIMEZONE,
        **inst_p,
        **usr_p,
    }
    result = await session.execute(
        text(
            f"""
            SELECT CAST(EXTRACT(HOUR FROM (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)) AS INTEGER) AS hour,
                   COALESCE(SUM(s.watched_seconds), 0) AS total_seconds
            FROM plex_playback_sessions s
            WHERE 1=1
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              AND LENGTH(s.start_time) >= 13
              {inst_w}{usr_w}
            GROUP BY 1
            ORDER BY 1
            """
        ),
        params,
    )
    rows = {
        int(r["hour"]): int(r["total_seconds"])
        for r in result.mappings().fetchall()
        if r["hour"] is not None
    }
    return [{"hour": h, "total_seconds": rows.get(h, 0)} for h in range(24)]


async def _get_activity_by_weekday(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return total watch time seconds grouped by weekday (0=Sun … 6=Sat)."""
    inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
    usr_w, usr_p = _user_instance_filter(
        user_ids, "instance_id", "CAST(account_id AS TEXT)"
    )
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        **_utc_window_params(start_date, end_date),
        "tz": brein_config.TIMEZONE,
        **inst_p,
        **usr_p,
    }
    result = await session.execute(
        text(
            f"""
            SELECT CAST(EXTRACT(DOW FROM (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date) AS INTEGER)
                   AS weekday,
                   COALESCE(SUM(s.watched_seconds), 0) AS total_seconds
            FROM plex_playback_sessions s
            WHERE 1=1
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              {inst_w}{usr_w}
            GROUP BY 1
            ORDER BY 1
            """
        ),
        params,
    )
    rows = {
        int(r["weekday"]): int(r["total_seconds"])
        for r in result.mappings().fetchall()
        if r["weekday"] is not None
    }
    return [{"weekday": d, "total_seconds": rows.get(d, 0)} for d in range(7)]


async def _get_watch_time_per_user_per_day(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return watch time seconds grouped by calendar date and user (local timezone)."""
    inst_w, inst_p = _instance_filter(instance_id, column="s.instance_id")
    usr_w, usr_p = _user_instance_filter(
        user_ids, "s.instance_id", "CAST(s.account_id AS TEXT)"
    )
    tz = brein_config.TIMEZONE
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        **_utc_window_params(start_date, end_date),
        "tz": tz,
        **inst_p,
        **usr_p,
    }
    result = await session.execute(
        text(
            f"""
            SELECT
                (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text AS day,
                s.instance_id,
                CAST(s.account_id AS TEXT) AS user_id,
                MAX(COALESCE(u.title, u.username, s.account_title, '')) AS user_name,
                COALESCE(SUM(s.watched_seconds), 0) AS total_seconds
            FROM plex_playback_sessions s
            LEFT JOIN plex_users u
                ON u.instance_id = s.instance_id
               AND u.user_id = s.account_id
               AND u.is_deleted = 0
            WHERE 1=1
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              AND LENGTH(s.start_time) >= 13
              AND s.watched_seconds > 0
              {inst_w}{usr_w}
            GROUP BY 1, s.instance_id, s.account_id
            ORDER BY 1, s.instance_id, s.account_id
            """
        ),
        params,
    )
    out: list[dict[str, Any]] = []
    for r in result.mappings().fetchall():
        iid = int(r["instance_id"]) if r["instance_id"] is not None else 0
        uid_str = str(r["user_id"]).strip() if r["user_id"] is not None else ""
        name = (r["user_name"] or "").strip()
        display_name = (
            name
            if name and name != uid_str
            else (f"User {uid_str}" if uid_str else "Unknown")
        )
        out.append(
            {
                "date": r["day"],
                "instance_id": iid,
                "user_id": uid_str,
                "display_name": display_name,
                "total_seconds": int(r["total_seconds"]),
            }
        )
    return out


async def _get_watch_time_by_media_type(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> dict[str, int]:
    """Watch time seconds grouped by media type (Movie, Episode, LiveTV, Other)."""
    inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
    usr_w, usr_p = _user_instance_filter(user_ids)
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        **_utc_window_params(start_date, end_date),
        "tz": brein_config.TIMEZONE,
        **inst_p,
        **usr_p,
    }
    result = await session.execute(
        text(
            f"""
            SELECT
              CASE
                WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('movie') THEN 'Movie'
                WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('episode') THEN 'Episode'
                WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('livetvchannel', 'program') THEN 'LiveTV'
                WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('track', 'album') THEN 'Audio'
                ELSE 'Other'
              END AS media_type,
              COALESCE(SUM(s.watched_seconds), 0) AS total_seconds
            FROM plex_playback_sessions s
            LEFT JOIN plex_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = s.rating_key
            WHERE (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              {inst_w}{usr_w}
            GROUP BY 1
            """
        ),
        params,
    )
    out: dict[str, int] = {
        "Movie": 0,
        "Episode": 0,
        "LiveTV": 0,
        "Audio": 0,
        "Other": 0,
    }
    for r in result.mappings().fetchall():
        mt = r["media_type"] or "Other"
        out[mt] = int(r["total_seconds"] or 0)
    return out


async def _get_watch_time_per_series(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    limit: int = 50,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Watch time seconds per TV series, sorted descending."""
    inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
    usr_w, usr_p = _user_instance_filter(user_ids)
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        **_utc_window_params(start_date, end_date),
        "limit": limit,
        "tz": brein_config.TIMEZONE,
        **inst_p,
        **usr_p,
    }
    result = await session.execute(
        text(
            f"""
            SELECT
              (s.instance_id, COALESCE(i.series_id, i.item_id, s.rating_key)) AS group_key,
              MAX(COALESCE(si.name, s.grandparent_title, i.name, s.rating_key)) AS label,
              COALESCE(SUM(s.watched_seconds), 0) AS total_seconds
            FROM plex_playback_sessions s
            LEFT JOIN plex_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = s.rating_key
            LEFT JOIN plex_items si
                ON si.instance_id = i.instance_id
               AND si.item_id = i.series_id
            WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('episode')
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              {inst_w}{usr_w}
            GROUP BY group_key
            ORDER BY total_seconds DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        {
            "label": r["label"] or "Unknown",
            "total_seconds": int(r["total_seconds"] or 0),
        }
        for r in result.mappings().fetchall()
    ]


async def _get_watch_time_per_movie(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    limit: int = 50,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Watch time seconds per movie, sorted descending."""
    inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
    usr_w, usr_p = _user_instance_filter(user_ids)
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        **_utc_window_params(start_date, end_date),
        "limit": limit,
        "tz": brein_config.TIMEZONE,
        **inst_p,
        **usr_p,
    }
    result = await session.execute(
        text(
            f"""
            SELECT
              (s.instance_id, COALESCE(i.item_id, s.rating_key)) AS group_key,
              MAX(COALESCE(i.name, s.title, s.rating_key)) AS label,
              COALESCE(SUM(s.watched_seconds), 0) AS total_seconds
            FROM plex_playback_sessions s
            LEFT JOIN plex_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = s.rating_key
            WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('movie')
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              {inst_w}{usr_w}
            GROUP BY group_key
            ORDER BY total_seconds DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        {
            "label": r["label"] or "Unknown",
            "total_seconds": int(r["total_seconds"] or 0),
        }
        for r in result.mappings().fetchall()
    ]


_PLEX_MEDIA_TYPE_CASE = """
                CASE
                  WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('movie') THEN 'Movie'
                  WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('episode') THEN 'Episode'
                  WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('livetvchannel', 'program') THEN 'LiveTV'
                  WHEN LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('track', 'album') THEN 'Audio'
                  ELSE 'Other'
                END
"""


async def get_media_type_sessions(
    start_date: str,
    end_date: str,
    media_type: str,
    instance_id: int | list[int] | None = None,
    limit: int = 100,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Sessions for one media-type bucket, using the same CASE the totals use."""
    async with get_session_factory()() as session:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "media_type": media_type,
            "limit": limit,
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        sql = f"""
            SELECT
                COALESCE(u.title, u.username, s.account_title, CAST(s.account_id AS TEXT)) AS user_display_name,
                COALESCE(i.name, s.title, s.rating_key) AS title,
                COALESCE(i.type, s.item_type) AS item_type,
                COALESCE(si.name, s.grandparent_title) AS series_name,
                i.parent_index_number AS season_number,
                i.index_number AS episode_number,
                ai.label AS instance_label,
                s.start_time AS played_at,
                s.watched_seconds
            FROM plex_playback_sessions s
            LEFT JOIN plex_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = s.rating_key
            LEFT JOIN plex_items si
                ON si.instance_id = i.instance_id
               AND si.item_id = i.series_id
            LEFT JOIN plex_users u
                ON u.instance_id = s.instance_id
               AND u.user_id = s.account_id
            LEFT JOIN app_instances ai ON ai.id = s.instance_id
            WHERE {_PLEX_MEDIA_TYPE_CASE} = :media_type
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              {inst_w}{usr_w}
            ORDER BY s.start_time DESC
            LIMIT :limit
        """
        result = await session.execute(text(sql), params)
        return [
            {
                "user_display_name": r["user_display_name"] or "Unknown",
                "title": r["title"] or "Unknown",
                "item_type": r["item_type"] or "",
                "series_name": r["series_name"] or "",
                "season_number": r["season_number"],
                "episode_number": r["episode_number"],
                "instance_label": r["instance_label"] or "",
                "played_at": r["played_at"] or "",
                "duration_seconds": int(r["watched_seconds"] or 0),
            }
            for r in result.mappings().fetchall()
        ]


async def get_time_sessions(
    start_date: str,
    end_date: str,
    period_type: str,
    period_value: int,
    instance_id: int | list[int] | None = None,
    limit: int = 100,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Sessions for a specific hour-of-day or day-of-week."""
    async with get_session_factory()() as session:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "pval": period_value,
            "limit": limit,
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        if period_type == "hour":
            period_where = (
                "AND CAST(EXTRACT(HOUR FROM (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)) AS INTEGER) = :pval"
                " AND LENGTH(s.start_time) >= 13"
            )
        else:
            period_where = "AND CAST(EXTRACT(DOW FROM (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date) AS INTEGER) = :pval"
        sql = f"""
            SELECT
                COALESCE(u.title, u.username, s.account_title, CAST(s.account_id AS TEXT)) AS user_display_name,
                COALESCE(i.name, s.title, s.rating_key) AS title,
                COALESCE(i.type, s.item_type) AS item_type,
                COALESCE(si.name, s.grandparent_title) AS series_name,
                i.parent_index_number AS season_number,
                i.index_number AS episode_number,
                ai.label AS instance_label,
                s.start_time AS played_at,
                s.watched_seconds
            FROM plex_playback_sessions s
            LEFT JOIN plex_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = s.rating_key
            LEFT JOIN plex_items si
                ON si.instance_id = i.instance_id
               AND si.item_id = i.series_id
            LEFT JOIN plex_users u
                ON u.instance_id = s.instance_id
               AND u.user_id = s.account_id
            LEFT JOIN app_instances ai ON ai.id = s.instance_id
            WHERE (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              {period_where}
              {inst_w}{usr_w}
            ORDER BY s.start_time DESC
            LIMIT :limit
        """
        result = await session.execute(text(sql), params)
        return [
            {
                "user_display_name": r["user_display_name"] or "Unknown",
                "title": r["title"] or "Unknown",
                "item_type": r["item_type"] or "",
                "series_name": r["series_name"] or "",
                "season_number": r["season_number"],
                "episode_number": r["episode_number"],
                "instance_label": r["instance_label"] or "",
                "played_at": r["played_at"] or "",
                "duration_seconds": int(r["watched_seconds"] or 0),
            }
            for r in result.mappings().fetchall()
        ]


async def get_all_sessions(
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """All sessions in a date range, optionally filtered by instance and user."""
    async with get_session_factory()() as session:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "limit": limit,
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        sql = f"""
            SELECT
                COALESCE(u.title, u.username, s.account_title, CAST(s.account_id AS TEXT)) AS user_display_name,
                COALESCE(i.name, s.title, s.rating_key) AS title,
                COALESCE(i.type, s.item_type) AS item_type,
                COALESCE(si.name, s.grandparent_title) AS series_name,
                i.parent_index_number AS season_number,
                i.index_number AS episode_number,
                ai.label AS instance_label,
                s.start_time AS played_at,
                s.watched_seconds
            FROM plex_playback_sessions s
            LEFT JOIN plex_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = s.rating_key
            LEFT JOIN plex_items si
                ON si.instance_id = s.instance_id
               AND si.item_id = i.series_id
            LEFT JOIN plex_users u
                ON u.instance_id = s.instance_id
               AND u.user_id = s.account_id
            LEFT JOIN app_instances ai ON ai.id = s.instance_id
            WHERE (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              {inst_w}{usr_w}
            ORDER BY s.start_time DESC
            LIMIT :limit
        """
        result = await session.execute(text(sql), params)
        return [
            {
                "user_display_name": r["user_display_name"] or "Unknown",
                "title": r["title"] or "Unknown",
                "item_type": r["item_type"] or "",
                "series_name": r["series_name"] or "",
                "season_number": r["season_number"],
                "episode_number": r["episode_number"],
                "instance_label": r["instance_label"] or "",
                "played_at": r["played_at"] or "",
                "duration_seconds": int(r["watched_seconds"] or 0),
            }
            for r in result.mappings().fetchall()
        ]


async def get_user_sessions(
    start_date: str,
    end_date: str,
    user_id: str,
    instance_id: int | list[int] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Play sessions for a specific user: item title, played_at, duration_seconds."""
    async with get_session_factory()() as session:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "user_id": user_id,
            "limit": limit,
            "tz": brein_config.TIMEZONE,
            **inst_p,
        }
        result = await session.execute(
            text(
                f"""
                SELECT
                    COALESCE(i.name, s.title, s.rating_key) AS title,
                    COALESCE(i.type, s.item_type) AS item_type,
                    COALESCE(si.name, s.grandparent_title) AS series_name,
                    i.parent_index_number AS season_number,
                    i.index_number AS episode_number,
                    ai.label AS instance_label,
                    s.start_time AS played_at,
                    s.watched_seconds
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                LEFT JOIN plex_items si
                    ON si.instance_id = i.instance_id
                   AND si.item_id = i.series_id
                LEFT JOIN app_instances ai ON ai.id = s.instance_id
                WHERE CAST(s.account_id AS TEXT) = :user_id
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}
                ORDER BY s.start_time DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [
            {
                "title": r["title"] or "Unknown",
                "item_type": r["item_type"] or "",
                "series_name": r["series_name"] or "",
                "season_number": r["season_number"],
                "episode_number": r["episode_number"],
                "instance_label": r["instance_label"] or "",
                "played_at": r["played_at"] or "",
                "duration_seconds": int(r["watched_seconds"] or 0),
            }
            for r in result.mappings().fetchall()
        ]


async def get_item_sessions(
    start_date: str,
    end_date: str,
    item_label: str,
    item_type: str,
    instance_id: int | list[int] | None = None,
    limit: int = 50,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Play sessions for a TV series or movie: user display name, played_at, duration_seconds."""
    async with get_session_factory()() as session:
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids)
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "item_label": item_label,
            "limit": limit,
            "tz": brein_config.TIMEZONE,
            **inst_p,
            **usr_p,
        }
        if item_type == "series":
            sql = f"""
                SELECT
                    COALESCE(u.title, u.username, s.account_title, CAST(s.account_id AS TEXT)) AS user_display_name,
                    COALESCE(i.name, s.title, s.rating_key) AS title,
                    COALESCE(i.type, s.item_type) AS item_type,
                    COALESCE(si.name, s.grandparent_title) AS series_name,
                    i.parent_index_number AS season_number,
                    i.index_number AS episode_number,
                    ai.label AS instance_label,
                    s.start_time AS played_at,
                    s.watched_seconds
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                LEFT JOIN plex_items si
                    ON si.instance_id = i.instance_id
                   AND si.item_id = i.series_id
                LEFT JOIN plex_users u
                    ON u.instance_id = s.instance_id
                   AND u.user_id = s.account_id
                LEFT JOIN app_instances ai ON ai.id = s.instance_id
                WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('episode')
                  AND COALESCE(si.name, s.grandparent_title, i.name, s.rating_key) = :item_label
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                ORDER BY s.start_time DESC
                LIMIT :limit
            """
        else:
            sql = f"""
                SELECT
                    COALESCE(u.title, u.username, s.account_title, CAST(s.account_id AS TEXT)) AS user_display_name,
                    COALESCE(i.name, s.title, s.rating_key) AS title,
                    COALESCE(i.type, s.item_type) AS item_type,
                    NULL AS series_name,
                    NULL AS season_number,
                    NULL AS episode_number,
                    ai.label AS instance_label,
                    s.start_time AS played_at,
                    s.watched_seconds
                FROM plex_playback_sessions s
                LEFT JOIN plex_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = s.rating_key
                LEFT JOIN plex_users u
                    ON u.instance_id = s.instance_id
                   AND u.user_id = s.account_id
                LEFT JOIN app_instances ai ON ai.id = s.instance_id
                WHERE LOWER(TRIM(COALESCE(i.type, s.item_type, ''))) IN ('movie')
                  AND COALESCE(i.name, s.title, s.rating_key) = :item_label
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                ORDER BY s.start_time DESC
                LIMIT :limit
            """
        result = await session.execute(text(sql), params)
        return [
            {
                "user_display_name": r["user_display_name"] or "Unknown",
                "title": r["title"] or "Unknown",
                "item_type": r["item_type"] or "",
                "series_name": r["series_name"] or "",
                "season_number": r["season_number"],
                "episode_number": r["episode_number"],
                "instance_label": r["instance_label"] or "",
                "played_at": r["played_at"] or "",
                "duration_seconds": int(r["watched_seconds"] or 0),
            }
            for r in result.mappings().fetchall()
        ]


async def get_all_metrics(
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return all dashboard metrics for the date range from Plex snapshot tables."""
    async with get_session_factory()() as session:
        totals = await _get_snapshot_totals(
            session, start_date, end_date, instance_id, user_ids
        )
        total_plays = totals["total_plays"]
        total_watch_time = totals["total_watch_time_seconds"]
        avg_session_seconds = (
            round(total_watch_time / total_plays) if total_plays > 0 else 0
        )
        if user_ids:
            total_episodes = await _get_total_watched_episodes(
                session, start_date, end_date, instance_id, user_ids
            )
            total_live_tv = await _get_total_watched_live_tv(
                session, start_date, end_date, instance_id, user_ids
            )
        else:
            total_episodes = totals["total_watched_episodes"]
            total_live_tv = totals["total_watched_live_tv"]
        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_plays": total_plays,
            "total_watch_time_seconds": total_watch_time,
            "avg_session_seconds": avg_session_seconds,
            "active_users_count": await _get_active_users_count(
                session, start_date, end_date, instance_id, user_ids
            ),
            "plays_per_user": await _get_plays_per_user(
                session, start_date, end_date, instance_id, user_ids
            ),
            "most_watched_items": await _get_most_watched_items(
                session, start_date, end_date, instance_id, user_ids=user_ids
            ),
            "watch_time_per_user": await _get_watch_time_per_user(
                session, start_date, end_date, instance_id, user_ids
            ),
            "total_watched_movies": await _get_total_watched_movies(
                session, start_date, end_date, instance_id, user_ids
            ),
            "total_watched_episodes": total_episodes,
            "total_watched_series": await _get_total_watched_series(
                session, start_date, end_date, instance_id, user_ids
            ),
            "total_watched_live_tv": total_live_tv,
            "watch_time_by_media_type": await _get_watch_time_by_media_type(
                session, start_date, end_date, instance_id, user_ids
            ),
            "watch_time_per_series": await _get_watch_time_per_series(
                session, start_date, end_date, instance_id, user_ids=user_ids
            ),
            "watch_time_per_movie": await _get_watch_time_per_movie(
                session, start_date, end_date, instance_id, user_ids=user_ids
            ),
            "streaming_by_hour": await _get_streaming_by_hour(
                session, start_date, end_date, instance_id, user_ids
            ),
            "activity_by_weekday": await _get_activity_by_weekday(
                session, start_date, end_date, instance_id, user_ids
            ),
            "watch_time_per_user_per_day": await _get_watch_time_per_user_per_day(
                session, start_date, end_date, instance_id, user_ids
            ),
        }
