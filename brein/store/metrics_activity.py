"""Aggregate activity metrics and get_all_metrics orchestrator for dashboard."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brein import config as brein_config
from brein.db import get_session_factory
from brein.store.metrics_helpers import (
    _UTC_TEXT_WINDOW,
    _UTC_TEXT_WINDOW_BARE,
    _date_range_where,
    _instance_filter,
    _user_instance_filter,
    _utc_window_params,
)
from brein.store.metrics_library import (
    _get_most_watched_items,
    _get_watch_time_by_media_type,
    _get_watch_time_per_movie,
    _get_watch_time_per_series,
)
from brein.store.metrics_users import (
    _get_active_users_count,
    _get_plays_per_user,
    _get_watch_time_per_user,
)


async def _get_total_plays(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> int:
    dr, dr_p = _date_range_where(start_date, end_date)
    inst_w, inst_p = _instance_filter(instance_id)
    if user_ids:
        usr_w, usr_p = _user_instance_filter(
            user_ids, "instance_id", "CAST(user_id AS TEXT)"
        )
        params = {**dr_p, **inst_p, **usr_p}
        result = await session.execute(
            text(
                f"SELECT COALESCE(SUM(plays), 0) FROM emby_metrics_snapshot_user WHERE 1=1{dr}{inst_w}{usr_w}"
            ),
            params,
        )
    else:
        params = {**dr_p, **inst_p}
        result = await session.execute(
            text(
                f"SELECT COALESCE(SUM(total_plays), 0) FROM emby_metrics_snapshot WHERE 1=1{dr}{inst_w}"
            ),
            params,
        )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def _get_total_watch_time_seconds(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> int:
    dr, dr_p = _date_range_where(start_date, end_date)
    inst_w, inst_p = _instance_filter(instance_id)
    if user_ids:
        usr_w, usr_p = _user_instance_filter(
            user_ids, "instance_id", "CAST(user_id AS TEXT)"
        )
        params = {**dr_p, **inst_p, **usr_p}
        result = await session.execute(
            text(
                f"SELECT COALESCE(SUM(watch_time_seconds), 0) FROM emby_metrics_snapshot_user WHERE 1=1{dr}{inst_w}{usr_w}"
            ),
            params,
        )
    else:
        params = {**dr_p, **inst_p}
        result = await session.execute(
            text(
                f"SELECT COALESCE(SUM(total_watch_time_seconds), 0)"
                f" FROM emby_metrics_snapshot WHERE 1=1{dr}{inst_w}"
            ),
            params,
        )
    row = result.fetchone()
    return int(row[0]) if row else 0


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
                SELECT COUNT(DISTINCT (s.instance_id, CAST(s.item_id AS TEXT)))
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                WHERE i.type = 'Movie'
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
                f" FROM emby_metrics_snapshot_item"
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
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                WHERE i.type = 'Episode'
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
                f" FROM emby_metrics_snapshot WHERE 1=1{dr}{inst_w}"
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
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                WHERE i.type = 'Episode'
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
                f"SELECT COUNT(DISTINCT (instance_id, series_id)) FROM emby_metrics_snapshot_item"
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
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                WHERE i.type IN ('LiveTvChannel', 'Program')
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
                f" FROM emby_metrics_snapshot WHERE 1=1{dr}{inst_w}"
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
    """Return total watch time seconds grouped by hour-of-day (0-23) in local timezone."""
    inst_w, inst_p = _instance_filter(instance_id)
    usr_w, usr_p = _user_instance_filter(
        user_ids, "instance_id", "CAST(user_id AS TEXT)"
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
            SELECT CAST(EXTRACT(HOUR FROM
                       (LEFT(start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)
                   ) AS INTEGER) AS hour,
                   COALESCE(SUM(duration_seconds), 0) AS total_seconds
            FROM emby_playback_sessions
            WHERE 1=1
              AND (LEFT(start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW_BARE}
              AND LENGTH(start_time) >= 13
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
    """Return total watch time seconds grouped by weekday (0=Sun … 6=Sat) in local timezone."""
    inst_w, inst_p = _instance_filter(instance_id)
    usr_w, usr_p = _user_instance_filter(
        user_ids, "instance_id", "CAST(user_id AS TEXT)"
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
            SELECT CAST(EXTRACT(DOW FROM
                       (LEFT(start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date
                   ) AS INTEGER) AS weekday,
                   COALESCE(SUM(duration_seconds), 0) AS total_seconds
            FROM emby_playback_sessions
            WHERE 1=1
              AND (LEFT(start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW_BARE}
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
        user_ids, "s.instance_id", "CAST(s.user_id AS TEXT)"
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
                CAST(s.user_id AS TEXT) AS user_id,
                MAX(u.name) AS user_name,
                COALESCE(SUM(s.duration_seconds), 0) AS total_seconds
            FROM emby_playback_sessions s
            LEFT JOIN emby_users u
                ON u.instance_id = s.instance_id
               AND u.user_item_id = CAST(s.user_id AS TEXT)
            WHERE 1=1
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
              AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
              {_UTC_TEXT_WINDOW}
              AND LENGTH(s.start_time) >= 13
              AND s.duration_seconds > 0
              {inst_w}{usr_w}
            GROUP BY 1, s.instance_id, s.user_id
            ORDER BY 1, s.instance_id, s.user_id
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


async def get_all_metrics(
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return all dashboard metrics for the date range from snapshot tables."""
    async with get_session_factory()() as session:
        total_plays = await _get_total_plays(
            session, start_date, end_date, instance_id, user_ids
        )
        total_watch_time = await _get_total_watch_time_seconds(
            session, start_date, end_date, instance_id, user_ids
        )
        avg_session_seconds = (
            round(total_watch_time / total_plays) if total_plays > 0 else 0
        )
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
            "total_watched_episodes": await _get_total_watched_episodes(
                session, start_date, end_date, instance_id, user_ids
            ),
            "total_watched_series": await _get_total_watched_series(
                session, start_date, end_date, instance_id, user_ids
            ),
            "total_watched_live_tv": await _get_total_watched_live_tv(
                session, start_date, end_date, instance_id, user_ids
            ),
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
