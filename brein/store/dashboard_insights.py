"""Cross-backend dashboard queries that read Emby, Jellyfin and Plex together.

The per-backend modules answer "what did this server do"; these answer questions
that only make sense across all of them at once — how many streams ran at the
same moment, who has stopped watching anywhere, what nobody has ever played.
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from brein import config as brein_config
from brein.db import get_session_factory
from brein.store.metrics_helpers import (
    _UTC_TEXT_WINDOW,
    _instance_filter,
    _user_instance_filter,
    _utc_window_params,
)

log = logging.getLogger(__name__)

# One arm per backend: (table, user column, duration column).
_SESSION_SOURCES = (
    ("emby_playback_sessions", "CAST(s.user_id AS TEXT)", "s.duration_seconds"),
    ("jellyfin_playback_sessions", "CAST(s.user_id AS TEXT)", "s.duration_seconds"),
    ("plex_playback_sessions", "CAST(s.account_id AS TEXT)", "s.watched_seconds"),
)

_LOCAL_DATE = "(LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text"


def _sessions_union(
    instance_id: int | list[int] | None,
    user_ids: list[str] | None,
) -> tuple[str, dict[str, Any]]:
    """A UNION ALL over the three session tables, filtered identically."""
    arms: list[str] = []
    params: dict[str, Any] = {}
    for index, (table, user_col, duration_col) in enumerate(_SESSION_SOURCES):
        inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
        usr_w, usr_p = _user_instance_filter(user_ids, "s.instance_id", user_col)
        # Each arm binds its own parameter names, or the three would collide.
        # The lookahead stops a rename matching a *prefix* of a longer name:
        # a plain str.replace of ":inst_1" also rewrote ":inst_10", producing
        # bind names no parameter matched once eleven users were selected.
        for key, value in {**inst_p, **usr_p}.items():
            params[f"{key}_{index}"] = value
        for key in {**inst_p, **usr_p}:
            pattern = re.compile(rf":{re.escape(key)}(?![0-9A-Za-z_])")
            inst_w = pattern.sub(f":{key}_{index}", inst_w)
            usr_w = pattern.sub(f":{key}_{index}", usr_w)
        arms.append(
            f"""
            SELECT s.instance_id,
                   s.start_time,
                   {duration_col} AS duration_seconds
            FROM {table} s
            WHERE {_LOCAL_DATE} >= :start_date
              AND {_LOCAL_DATE} <= :end_date
              {_UTC_TEXT_WINDOW}
              AND LENGTH(s.start_time) >= 13
              AND {duration_col} > 0
              {inst_w}{usr_w}
            """
        )
    return " UNION ALL ".join(arms), params


async def get_concurrency_by_day(
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Peak simultaneous streams per calendar day, across every backend.

    Sessions become +1 / -1 events at their start and end, and a running sum
    over those events in time order gives the number playing at each moment.
    Ends are ordered before starts at the same instant, so a stream that stops
    exactly as another begins is not counted twice.
    """
    # Scan a day wider than asked. A stream that began the previous evening is
    # still playing after midnight and belongs to the first day's peak, and one
    # that starts on the last day may only end on the next — both are dropped
    # by a scan bounded exactly, and the second invents a day of its own.
    scan_from = (date.fromisoformat(start_date) - timedelta(days=1)).isoformat()
    scan_to = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
    union, params = _sessions_union(instance_id, user_ids)
    params.update(
        {
            "start_date": scan_from,
            "end_date": scan_to,
            # The sargable prefilter beside the local-date predicate, which
            # can use no index. Padded from the already-widened scan bounds,
            # so it can only ever be looser than the predicate it helps.
            **_utc_window_params(scan_from, scan_to),
            "range_start": start_date,
            "range_end": end_date,
            "midnight_from": datetime.fromisoformat(start_date),
            "midnight_to": datetime.fromisoformat(end_date),
            "tz": brein_config.TIMEZONE,
        }
    )
    sql = f"""
        WITH sessions AS ({union}),
        events AS (
            SELECT LEFT(start_time, 19)::timestamp AS at, 1 AS delta
            FROM sessions
            UNION ALL
            SELECT LEFT(start_time, 19)::timestamp
                     + make_interval(secs => duration_seconds) AS at,
                   -1 AS delta
            FROM sessions
            UNION ALL
            -- A weightless event at each requested day's local midnight, so
            -- the running count is sampled there. Without it a day is only
            -- observed at its own starts and ends, and the end of a stream
            -- that began the night before reads the count *after* it was
            -- subtracted — a day whose only event is that end reported 0.
            SELECT (midnight AT TIME ZONE :tz AT TIME ZONE 'UTC') AS at, 0 AS delta
            FROM generate_series(CAST(:midnight_from AS timestamp),
                                 CAST(:midnight_to AS timestamp),
                                 interval '1 day') AS midnight
        ),
        running AS (
            SELECT at,
                   SUM(delta) OVER (ORDER BY at, delta ROWS UNBOUNDED PRECEDING)
                     AS concurrent
            FROM events
        )
        SELECT day, peak FROM (
            SELECT (at AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text AS day,
                   MAX(concurrent) AS peak
            FROM running
            GROUP BY 1
        ) per_day
        -- Trim the padding day back off: the wider scan exists to carry
        -- overlap across the edges, not to report days nobody asked for.
        WHERE day BETWEEN :range_start AND :range_end
        ORDER BY day
    """
    async with get_session_factory()() as session:
        result = await session.execute(text(sql), params)
        return [
            {"date": r["day"], "peak": int(r["peak"] or 0)}
            for r in result.mappings().fetchall()
            if r["day"] is not None
        ]


async def get_idle_users(
    days: int = 30,
    instance_id: int | list[int] | None = None,
) -> list[dict[str, Any]]:
    """Users whose last recorded playback is older than `days` — or never.

    Last-watched comes from the session tables rather than the servers' own
    "last activity" field, because Plex stores no such column and the three
    would otherwise not be comparable.
    """
    inst_w, inst_p = _instance_filter(instance_id, "u.instance_id")
    # The same filter, against the session tables' own column: without it the
    # three were aggregated in full even when one server was asked about.
    sessions_w, _ = _instance_filter(instance_id, "instance_id")
    params: dict[str, Any] = {"days": int(days), **inst_p}
    sql = f"""
        WITH watched AS (
            -- The length guard matters: the HAVING below casts this value to
            -- a timestamp, and one short or malformed start_time would take
            -- the whole endpoint down with it.
            SELECT instance_id, CAST(user_id AS TEXT) AS user_key,
                   MAX(start_time) AS last_played
            FROM emby_playback_sessions
            WHERE LENGTH(start_time) >= 19 {sessions_w} GROUP BY 1, 2
            UNION ALL
            SELECT instance_id, CAST(user_id AS TEXT), MAX(start_time)
            FROM jellyfin_playback_sessions
            WHERE LENGTH(start_time) >= 19 {sessions_w} GROUP BY 1, 2
            UNION ALL
            SELECT instance_id, CAST(account_id AS TEXT), MAX(start_time)
            FROM plex_playback_sessions
            WHERE LENGTH(start_time) >= 19 {sessions_w} GROUP BY 1, 2
        ),
        people AS (
            -- Emby sessions key on user_item_id, but it is nullable and the
            -- backfill can lag; matching either id keeps a user who has
            -- watched from being reported idle.
            SELECT u.instance_id, CAST(u.user_item_id AS TEXT) AS user_key,
                   CAST(u.user_id AS TEXT) AS alt_key,
                   u.name AS display_name, u.last_activity_date
            FROM emby_users u
            WHERE u.is_deleted = 0 {inst_w}
            UNION ALL
            SELECT u.instance_id, CAST(u.user_id AS TEXT), CAST(u.user_id AS TEXT),
                   u.name, u.last_activity_date
            FROM jellyfin_users u
            WHERE u.is_deleted = 0 {inst_w}
            UNION ALL
            SELECT u.instance_id, CAST(u.user_id AS TEXT), CAST(u.user_id AS TEXT),
                   COALESCE(u.title, u.username), NULL
            FROM plex_users u
            WHERE u.is_deleted = 0 {inst_w}
        )
        SELECT p.instance_id,
               ai.label AS instance_label,
               p.user_key AS user_id,
               p.display_name,
               p.last_activity_date,
               MAX(w.last_played) AS last_played
        FROM people p
        LEFT JOIN watched w
            ON w.instance_id = p.instance_id
           AND (w.user_key = p.user_key OR w.user_key = p.alt_key)
        LEFT JOIN app_instances ai ON ai.id = p.instance_id
        -- Grouped on the user key, not only the name. Two accounts on one
        -- server can share a display name (Plex home users often do, and
        -- Plex has no last_activity_date to tell them apart), and grouping
        -- without the key merged them — MAX() then lent the active one's
        -- timestamp to the idle one, which never appeared in the list.
        GROUP BY p.instance_id, ai.label, p.user_key, p.display_name,
                 p.last_activity_date
        HAVING MAX(w.last_played) IS NULL
            OR LEFT(MAX(w.last_played), 19)::timestamp
                 < NOW() AT TIME ZONE 'UTC' - (:days * INTERVAL '1 day')
        ORDER BY MAX(w.last_played) NULLS FIRST
    """
    async with get_session_factory()() as session:
        result = await session.execute(text(sql), params)
        return [
            {
                "instance_id": int(r["instance_id"]),
                "instance_label": r["instance_label"] or "",
                "user_id": r["user_id"] or "",
                "display_name": r["display_name"] or "Unknown",
                "last_played": r["last_played"] or "",
                "last_activity_date": r["last_activity_date"] or "",
            }
            for r in result.mappings().fetchall()
        ]


# Item types worth reporting on: a season or a channel is not "content nobody
# watched" in any useful sense.
_UNWATCHED_TYPES = ("Movie", "Episode")


async def get_unwatched_summary(
    instance_id: int | list[int] | None = None,
) -> list[dict[str, Any]]:
    """Per instance and type: how much of the library has never been played."""
    inst_w, inst_p = _instance_filter(instance_id, "i.instance_id")
    sessions_w, _ = _instance_filter(instance_id, "instance_id")
    params: dict[str, Any] = {**inst_p}
    sql = f"""
        WITH library AS (
            SELECT i.instance_id, i.type, i.item_id
            FROM emby_items i
            WHERE i.type IN ('Movie', 'Episode') {inst_w}
            UNION ALL
            SELECT i.instance_id, i.type, i.item_id
            FROM jellyfin_items i
            WHERE i.type IN ('Movie', 'Episode') {inst_w}
            UNION ALL
            SELECT i.instance_id, i.type, i.item_id
            FROM plex_items i
            WHERE i.type IN ('movie', 'episode', 'Movie', 'Episode') {inst_w}
        ),
        played AS (
            SELECT instance_id, CAST(item_id AS TEXT) AS item_id
            FROM emby_playback_sessions WHERE TRUE {sessions_w}
            UNION ALL
            SELECT instance_id, CAST(item_id AS TEXT) FROM jellyfin_playback_sessions
            WHERE TRUE {sessions_w}
            UNION ALL
            SELECT instance_id, rating_key FROM plex_playback_sessions
            WHERE TRUE {sessions_w}
        )
        SELECT l.instance_id,
               ai.label AS instance_label,
               INITCAP(l.type) AS item_type,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE p.item_id IS NULL) AS unwatched
        FROM library l
        LEFT JOIN (SELECT DISTINCT instance_id, item_id FROM played) p
            ON p.instance_id = l.instance_id AND p.item_id = l.item_id
        LEFT JOIN app_instances ai ON ai.id = l.instance_id
        GROUP BY 1, 2, 3
        ORDER BY 1, 3
    """
    async with get_session_factory()() as session:
        result = await session.execute(text(sql), params)
        return [
            {
                "instance_id": int(r["instance_id"]),
                "instance_label": r["instance_label"] or "",
                "item_type": r["item_type"] or "",
                "total": int(r["total"] or 0),
                "unwatched": int(r["unwatched"] or 0),
            }
            for r in result.mappings().fetchall()
        ]


async def get_unwatched_items(
    item_type: str = "Movie",
    instance_id: int | list[int] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """The titles nobody has played, by title.

    Not "newest first", though the tab once said so: the only timestamp the
    item tables carry is `updated_at`. The bulk upsert now leaves unchanged
    rows alone, so it says when the row's metadata last changed — closer,
    but still not when the item was added, and for anything synced before
    that change it is still the sync-batch stamp. Sorting on it produced
    sync-batch order dressed up as recency.
    """
    wanted = item_type.title()
    if wanted not in _UNWATCHED_TYPES:
        wanted = "Movie"
    inst_w, inst_p = _instance_filter(instance_id, "i.instance_id")
    sessions_w, _ = _instance_filter(instance_id, "instance_id")
    params: dict[str, Any] = {
        "wanted": wanted,
        # Plex stores its types lowercase; matching both beats INITCAP(), which
        # has to be computed for every row of a 130k-item table.
        "wanted_lower": wanted.lower(),
        "limit": int(limit),
        **inst_p,
    }
    sql = f"""
        WITH library AS (
            SELECT i.instance_id, i.type, i.item_id, i.name, i.series_id,
                   i.parent_index_number, i.index_number, i.updated_at
            FROM emby_items i
            WHERE i.type IN (:wanted, :wanted_lower) {inst_w}
            UNION ALL
            SELECT i.instance_id, i.type, i.item_id, i.name, i.series_id,
                   i.parent_index_number, i.index_number, i.updated_at
            FROM jellyfin_items i
            WHERE i.type IN (:wanted, :wanted_lower) {inst_w}
            UNION ALL
            SELECT i.instance_id, i.type, i.item_id, i.name, i.series_id,
                   i.parent_index_number, i.index_number, i.updated_at
            FROM plex_items i
            WHERE i.type IN (:wanted, :wanted_lower) {inst_w}
        ),
        played AS (
            SELECT DISTINCT instance_id, CAST(item_id AS TEXT) AS item_id
            FROM emby_playback_sessions WHERE TRUE {sessions_w}
            UNION
            SELECT DISTINCT instance_id, CAST(item_id AS TEXT)
            FROM jellyfin_playback_sessions WHERE TRUE {sessions_w}
            UNION
            SELECT DISTINCT instance_id, rating_key FROM plex_playback_sessions
            WHERE TRUE {sessions_w}
        )
        SELECT l.instance_id,
               ai.label AS instance_label,
               l.item_id,
               l.name AS title,
               l.parent_index_number AS season_number,
               l.index_number AS episode_number,
               l.updated_at
        FROM library l
        LEFT JOIN played p
            ON p.instance_id = l.instance_id AND p.item_id = l.item_id
        LEFT JOIN app_instances ai ON ai.id = l.instance_id
        WHERE p.item_id IS NULL
        ORDER BY l.name, l.item_id
        LIMIT :limit
    """
    async with get_session_factory()() as session:
        result = await session.execute(text(sql), params)
        return [
            {
                "instance_id": int(r["instance_id"]),
                "instance_label": r["instance_label"] or "",
                "item_id": str(r["item_id"]),
                "title": r["title"] or "Unknown",
                "season_number": r["season_number"],
                "episode_number": r["episode_number"],
                "updated_at": r["updated_at"] or "",
            }
            for r in result.mappings().fetchall()
        ]
