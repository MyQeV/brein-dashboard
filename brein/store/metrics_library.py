"""Library item and media-type watch-time queries for dashboard metrics."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brein import config as brein_config
from brein.store.metrics_helpers import (
    _UTC_TEXT_WINDOW,
    _date_range_where,
    _instance_filter,
    _user_instance_filter,
    _utc_window_params,
)


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
                    CAST(s.item_id AS TEXT) AS item_id,
                    MAX(i.name) AS item_name,
                    MAX(i.type) AS item_type,
                    CASE
                        WHEN MAX(i.type) = 'Episode'
                             AND MAX(si.name) IS NOT NULL
                             AND MAX(si.name) != ''
                        THEN MAX(si.name) || ' \u2013 ' || COALESCE(MAX(i.name), CAST(s.item_id AS TEXT))
                        ELSE COALESCE(MAX(i.name), CAST(s.item_id AS TEXT))
                    END AS display_label,
                    COUNT(*) AS plays
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                LEFT JOIN emby_items si
                    ON si.instance_id = i.instance_id
                   AND si.item_id = i.series_id
                WHERE (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text >= :start_date
                  AND (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date::text <= :end_date
                  {_UTC_TEXT_WINDOW}
                  {inst_w}{usr_w}
                GROUP BY s.instance_id, s.item_id
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
                FROM emby_metrics_snapshot_item
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


async def _get_watch_time_by_media_type(
    session: AsyncSession,
    start_date: str,
    end_date: str,
    instance_id: int | list[int] | None = None,
    user_ids: list[str] | None = None,
) -> dict[str, int]:
    """Watch time seconds grouped by media type (Movie, Episode, LiveTV, Audio, Other)."""
    inst_w, inst_p = _instance_filter(instance_id, "s.instance_id")
    usr_w, usr_p = _user_instance_filter(user_ids)
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
              CASE
                WHEN i.type = 'Movie' THEN 'Movie'
                WHEN i.type = 'Episode' THEN 'Episode'
                WHEN i.type IN ('LiveTvChannel', 'TvChannel', 'Program') THEN 'LiveTV'
                WHEN i.type = 'Audio' THEN 'Audio'
                ELSE 'Other'
              END AS media_type,
              COALESCE(SUM(s.duration_seconds), 0) AS total_seconds
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = CAST(s.item_id AS TEXT)
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
              (s.instance_id, COALESCE(i.series_id, i.item_id, CAST(s.item_id AS TEXT))) AS group_key,
              MAX(COALESCE(si.name, i.name, CAST(s.item_id AS TEXT))) AS label,
              COALESCE(SUM(s.duration_seconds), 0) AS total_seconds
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = CAST(s.item_id AS TEXT)
            LEFT JOIN emby_items si
                ON si.instance_id = i.instance_id
               AND si.item_id = i.series_id
            WHERE i.type = 'Episode'
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
              (s.instance_id, COALESCE(i.item_id, CAST(s.item_id AS TEXT))) AS group_key,
              MAX(COALESCE(i.name, CAST(s.item_id AS TEXT))) AS label,
              COALESCE(SUM(s.duration_seconds), 0) AS total_seconds
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = CAST(s.item_id AS TEXT)
            WHERE i.type = 'Movie'
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
