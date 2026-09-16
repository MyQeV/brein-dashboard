"""Playback snapshot rebuild and session queries for dashboard metrics."""

import asyncio
import logging
from typing import Any

from sqlalchemy import text

from brein import config as brein_config
from brein.db import get_session_factory
from brein.store.metrics_helpers import (
    _LIVE_TV_SQL,
    _UTC_TEXT_WINDOW,
    _instance_filter,
    _local_date_expr,
    _snapshot_since_params,
    _user_instance_filter,
    _utc_window_params,
)

log = logging.getLogger(__name__)

_rebuild_lock = asyncio.Lock()


async def rebuild_snapshots(
    instance_id: int | None = None, since_date: str | None = None
) -> None:
    """Re-populate the three snapshot tables from sessions + items + users.

    With ``since_date`` (a local YYYY-MM-DD stat_date) only that day and later
    are deleted and re-aggregated; without it every row is. The three tables
    share one bound and one transaction, so they never disagree with each
    other. Serialized via _rebuild_lock so concurrent callers don't race on
    DELETE/INSERT and trip a unique-violation.
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

        # --- emby_metrics_snapshot (daily totals) ---
        await session.execute(
            text("DELETE FROM emby_metrics_snapshot" + inst_del_filter),
            inst_del_params,
        )
        await session.execute(
            text(
                f"""
                INSERT INTO emby_metrics_snapshot
                    (stat_date, instance_id, total_plays, total_watch_time_seconds,
                     total_movies, total_episodes, total_live_tv)
                SELECT
                    {ld} AS stat_date,
                    s.instance_id,
                    COUNT(*) AS total_plays,
                    COALESCE(SUM(s.duration_seconds), 0) AS total_watch_time_seconds,
                    SUM(CASE WHEN i.type = 'Movie' THEN 1 ELSE 0 END) AS total_movies,
                    SUM(CASE WHEN i.type = 'Episode' THEN 1 ELSE 0 END) AS total_episodes,
                    SUM(CASE WHEN i.type IN {_LIVE_TV_SQL} THEN 1 ELSE 0 END) AS total_live_tv
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id AND i.item_id = CAST(s.item_id AS TEXT)
                WHERE 1=1 {inst_filter}{since_filter}
                GROUP BY {ld}, s.instance_id
                """
            ),
            sel_params,
        )

        # --- emby_metrics_snapshot_user (daily per-user) ---
        await session.execute(
            text("DELETE FROM emby_metrics_snapshot_user" + inst_del_filter),
            inst_del_params,
        )
        await session.execute(
            text(
                f"""
                INSERT INTO emby_metrics_snapshot_user
                    (stat_date, instance_id, user_id, user_name, plays, watch_time_seconds)
                SELECT
                    {ld} AS stat_date,
                    s.instance_id,
                    CAST(s.user_id AS TEXT) AS user_id,
                    u.name,
                    COUNT(*) AS plays,
                    COALESCE(SUM(s.duration_seconds), 0) AS watch_time_seconds
                FROM emby_playback_sessions s
                LEFT JOIN emby_users u
                    ON u.instance_id = s.instance_id
                   AND u.user_item_id = CAST(s.user_id AS TEXT)
                   AND u.is_deleted = 0
                WHERE 1=1 {inst_filter}{since_filter}
                GROUP BY {ld}, s.instance_id, s.user_id, u.name
                """
            ),
            sel_params,
        )

        # --- emby_metrics_snapshot_item (daily per-item, denormalized) ---
        await session.execute(
            text("DELETE FROM emby_metrics_snapshot_item" + inst_del_filter),
            inst_del_params,
        )
        await session.execute(
            text(
                f"""
                INSERT INTO emby_metrics_snapshot_item
                    (stat_date, instance_id, item_id, item_name, item_type,
                     series_id, series_name, display_label, plays)
                SELECT
                    {ld} AS stat_date,
                    s.instance_id,
                    CAST(s.item_id AS TEXT) AS item_id,
                    i.name,
                    i.type,
                    i.series_id,
                    series_item.name,
                    CASE
                        WHEN i.type = 'Episode'
                             AND series_item.name IS NOT NULL
                             AND series_item.name != ''
                        THEN series_item.name || ' – ' || COALESCE(i.name, CAST(s.item_id AS TEXT))
                        ELSE COALESCE(i.name, CAST(s.item_id AS TEXT))
                    END,
                    COUNT(*) AS plays
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                LEFT JOIN emby_items series_item
                    ON series_item.instance_id = i.instance_id
                   AND series_item.item_id = i.series_id
                WHERE 1=1 {inst_filter}{since_filter}
                GROUP BY {ld}, s.instance_id, s.item_id,
                         i.name, i.type, i.series_id, series_item.name
                """
            ),
            sel_params,
        )

        await session.commit()
        log.info(
            "Dashboard snapshots rebuilt%s%s",
            f" for instance_id={instance_id}" if instance_id is not None else "",
            f" since {since_date}" if since_date else "",
        )


_EMBY_MEDIA_TYPE_CASE = f"""
                CASE
                  WHEN i.type = 'Movie' THEN 'Movie'
                  WHEN i.type = 'Episode' THEN 'Episode'
                  WHEN i.type IN {_LIVE_TV_SQL} THEN 'LiveTV'
                  WHEN i.type = 'Audio' THEN 'Audio'
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
                COALESCE(u.name, CAST(s.user_id AS TEXT)) AS user_display_name,
                COALESCE(i.name, CAST(s.item_id AS TEXT)) AS title,
                i.type AS item_type,
                si.name AS series_name,
                i.parent_index_number AS season_number,
                i.index_number AS episode_number,
                ai.label AS instance_label,
                s.start_time AS played_at,
                s.duration_seconds
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = CAST(s.item_id AS TEXT)
            LEFT JOIN emby_items si
                ON si.instance_id = i.instance_id
               AND si.item_id = i.series_id
            LEFT JOIN emby_users u
                ON u.instance_id = s.instance_id
               AND u.user_item_id = CAST(s.user_id AS TEXT)
            LEFT JOIN app_instances ai ON ai.id = s.instance_id
            WHERE {_EMBY_MEDIA_TYPE_CASE} = :media_type
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
                "duration_seconds": int(r["duration_seconds"] or 0),
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
        tz = brein_config.TIMEZONE
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "pval": period_value,
            "limit": limit,
            "tz": tz,
            **inst_p,
            **usr_p,
        }
        if period_type == "hour":
            period_where = (
                "AND CAST(EXTRACT(HOUR FROM"
                " (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)"
                ") AS INTEGER) = :pval"
                " AND LENGTH(s.start_time) >= 13"
            )
        else:
            period_where = (
                "AND CAST(EXTRACT(DOW FROM"
                " (LEFT(s.start_time, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date"
                ") AS INTEGER) = :pval"
            )
        sql = f"""
            SELECT
                COALESCE(u.name, CAST(s.user_id AS TEXT)) AS user_display_name,
                COALESCE(i.name, CAST(s.item_id AS TEXT)) AS title,
                i.type AS item_type,
                si.name AS series_name,
                i.parent_index_number AS season_number,
                i.index_number AS episode_number,
                ai.label AS instance_label,
                s.start_time AS played_at,
                s.duration_seconds
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = CAST(s.item_id AS TEXT)
            LEFT JOIN emby_items si
                ON si.instance_id = i.instance_id
               AND si.item_id = i.series_id
            LEFT JOIN emby_users u
                ON u.instance_id = s.instance_id
               AND u.user_item_id = CAST(s.user_id AS TEXT)
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
                "duration_seconds": int(r["duration_seconds"] or 0),
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
                COALESCE(u.name, CAST(s.user_id AS TEXT)) AS user_display_name,
                COALESCE(i.name, CAST(s.item_id AS TEXT)) AS title,
                i.type AS item_type,
                si.name AS series_name,
                i.parent_index_number AS season_number,
                i.index_number AS episode_number,
                ai.label AS instance_label,
                s.start_time AS played_at,
                s.duration_seconds
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
                ON i.instance_id = s.instance_id
               AND i.item_id = CAST(s.item_id AS TEXT)
            LEFT JOIN emby_items si
                ON si.instance_id = s.instance_id
               AND si.item_id = i.series_id
            LEFT JOIN emby_users u
                ON u.instance_id = s.instance_id
               AND u.user_item_id = CAST(s.user_id AS TEXT)
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
                "duration_seconds": int(r["duration_seconds"] or 0),
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
        tz = brein_config.TIMEZONE
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "user_id": user_id,
            "limit": limit,
            "tz": tz,
            **inst_p,
        }
        result = await session.execute(
            text(
                f"""
                SELECT
                    COALESCE(i.name, CAST(s.item_id AS TEXT)) AS title,
                    i.type AS item_type,
                    si.name AS series_name,
                    i.parent_index_number AS season_number,
                    i.index_number AS episode_number,
                    ai.label AS instance_label,
                    s.start_time AS played_at,
                    s.duration_seconds
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                LEFT JOIN emby_items si
                    ON si.instance_id = i.instance_id
                   AND si.item_id = i.series_id
                LEFT JOIN app_instances ai ON ai.id = s.instance_id
                WHERE CAST(s.user_id AS TEXT) = :user_id
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
                "duration_seconds": int(r["duration_seconds"] or 0),
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
        tz = brein_config.TIMEZONE
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            **_utc_window_params(start_date, end_date),
            "item_label": item_label,
            "limit": limit,
            "tz": tz,
            **inst_p,
            **usr_p,
        }
        if item_type == "series":
            sql = f"""
                SELECT
                    COALESCE(u.name, CAST(s.user_id AS TEXT)) AS user_display_name,
                    COALESCE(i.name, CAST(s.item_id AS TEXT)) AS title,
                    i.type AS item_type,
                    si.name AS series_name,
                    i.parent_index_number AS season_number,
                    i.index_number AS episode_number,
                    ai.label AS instance_label,
                    s.start_time AS played_at,
                    s.duration_seconds
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                LEFT JOIN emby_items si
                    ON si.instance_id = i.instance_id
                   AND si.item_id = i.series_id
                LEFT JOIN emby_users u
                    ON u.instance_id = s.instance_id
                   AND u.user_item_id = CAST(s.user_id AS TEXT)
                LEFT JOIN app_instances ai ON ai.id = s.instance_id
                WHERE i.type = 'Episode'
                  AND COALESCE(si.name, i.name, CAST(s.item_id AS TEXT)) = :item_label
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
                    COALESCE(u.name, CAST(s.user_id AS TEXT)) AS user_display_name,
                    COALESCE(i.name, CAST(s.item_id AS TEXT)) AS title,
                    i.type AS item_type,
                    NULL AS series_name,
                    NULL AS season_number,
                    NULL AS episode_number,
                    ai.label AS instance_label,
                    s.start_time AS played_at,
                    s.duration_seconds
                FROM emby_playback_sessions s
                LEFT JOIN emby_items i
                    ON i.instance_id = s.instance_id
                   AND i.item_id = CAST(s.item_id AS TEXT)
                LEFT JOIN emby_users u
                    ON u.instance_id = s.instance_id
                   AND u.user_item_id = CAST(s.user_id AS TEXT)
                LEFT JOIN app_instances ai ON ai.id = s.instance_id
                WHERE i.type = 'Movie'
                  AND COALESCE(i.name, CAST(s.item_id AS TEXT)) = :item_label
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
                "duration_seconds": int(r["duration_seconds"] or 0),
            }
            for r in result.mappings().fetchall()
        ]
