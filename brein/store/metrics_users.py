"""Per-user play and watch-time queries for dashboard metrics."""

from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brein.config import TIMEZONE
from brein.store.metrics_helpers import (
    _date_range_where,
    _instance_filter,
    _local_date_expr,
    _user_instance_filter,
)


async def get_user_daily_watch_time(
    session: AsyncSession,
    instance_id: int,
    user_id: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Daily plays + watch-time for one user from emby_metrics_snapshot_user."""
    result = await session.execute(
        text(
            """
            SELECT stat_date,
                   COALESCE(SUM(plays), 0) AS plays,
                   COALESCE(SUM(watch_time_seconds), 0) AS watch_time_seconds
            FROM emby_metrics_snapshot_user
            WHERE instance_id = :instance_id
              AND user_id = :user_id
              AND stat_date >= :start_date
              AND stat_date <= :end_date
            GROUP BY stat_date
            ORDER BY stat_date ASC
            """
        ),
        {
            "instance_id": instance_id,
            "user_id": str(user_id),
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    return [
        {
            "stat_date": str(r["stat_date"]),
            "plays": int(r["plays"] or 0),
            "watch_time_seconds": int(r["watch_time_seconds"] or 0),
        }
        for r in result.mappings().fetchall()
    ]


async def get_user_recent_items(
    session: AsyncSession,
    instance_id: int,
    user_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Most recent activity-log entries for a user, with item metadata if known."""
    result = await session.execute(
        text(
            """
            SELECT a.entry_id, a.name AS entry_name, a.type AS entry_type,
                   a.item_id, a.date, a.overview,
                   i.name AS item_name, i.type AS item_type, i.series_id
            FROM emby_activity_log_entries a
            LEFT JOIN emby_items i
              ON i.instance_id = a.instance_id
              AND i.item_id = CAST(a.item_id AS TEXT)
            WHERE a.instance_id = :instance_id
              AND CAST(a.user_id AS TEXT) = :user_id
            ORDER BY a.entry_id DESC
            LIMIT :limit
            """
        ),
        {
            "instance_id": instance_id,
            "user_id": str(user_id),
            "limit": int(limit),
        },
    )
    return [dict(r) for r in result.mappings().fetchall()]


async def get_user_top_items(
    session: AsyncSession,
    instance_id: int,
    user_id: str,
    start_date: str,
    end_date: str,
    kind: Literal["series", "movies"] = "series",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Top series or movies for a user by total watch time in the date range."""
    ld = _local_date_expr("s.start_time")
    if kind == "series":
        query = f"""
            SELECT i.series_id AS group_key,
                   COALESCE(MAX(parent.name), 'Unknown series') AS display_name,
                   SUM(s.duration_seconds) AS total_seconds,
                   COUNT(*) AS plays
            FROM emby_playback_sessions s
            JOIN emby_items i
              ON i.instance_id = s.instance_id
              AND i.item_id = CAST(s.item_id AS TEXT)
            LEFT JOIN emby_items parent
              ON parent.instance_id = i.instance_id
              AND parent.item_id = i.series_id
            WHERE s.instance_id = :instance_id
              AND CAST(s.user_id AS TEXT) = :user_id
              AND i.series_id IS NOT NULL
              AND {ld} BETWEEN :start_date AND :end_date
            GROUP BY i.series_id
            ORDER BY total_seconds DESC
            LIMIT :limit
        """
    else:
        query = f"""
            SELECT i.item_id AS group_key,
                   COALESCE(MAX(i.name), 'Unknown movie') AS display_name,
                   SUM(s.duration_seconds) AS total_seconds,
                   COUNT(*) AS plays
            FROM emby_playback_sessions s
            JOIN emby_items i
              ON i.instance_id = s.instance_id
              AND i.item_id = CAST(s.item_id AS TEXT)
            WHERE s.instance_id = :instance_id
              AND CAST(s.user_id AS TEXT) = :user_id
              AND i.type = 'Movie'
              AND {ld} BETWEEN :start_date AND :end_date
            GROUP BY i.item_id
            ORDER BY total_seconds DESC
            LIMIT :limit
        """
    result = await session.execute(
        text(query),
        {
            "instance_id": instance_id,
            "user_id": str(user_id),
            "start_date": start_date,
            "end_date": end_date,
            "limit": int(limit),
            "tz": TIMEZONE,
        },
    )
    return [
        {
            "group_key": str(r["group_key"]) if r["group_key"] else "",
            "display_name": (r["display_name"] or "").strip() or "Unknown",
            "total_seconds": int(r["total_seconds"] or 0),
            "plays": int(r["plays"] or 0),
        }
        for r in result.mappings().fetchall()
    ]


async def get_user_watch_time_by_type(
    session: AsyncSession,
    instance_id: int,
    user_id: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Watch time grouped by item type (Movie / Episode / etc.) for a user."""
    ld = _local_date_expr("s.start_time")
    result = await session.execute(
        text(
            f"""
            SELECT COALESCE(i.type, 'Unknown') AS item_type,
                   SUM(s.duration_seconds) AS total_seconds,
                   COUNT(*) AS plays
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
              ON i.instance_id = s.instance_id
              AND i.item_id = CAST(s.item_id AS TEXT)
            WHERE s.instance_id = :instance_id
              AND CAST(s.user_id AS TEXT) = :user_id
              AND {ld} BETWEEN :start_date AND :end_date
            GROUP BY i.type
            ORDER BY total_seconds DESC
            """
        ),
        {
            "instance_id": instance_id,
            "user_id": str(user_id),
            "start_date": start_date,
            "end_date": end_date,
            "tz": TIMEZONE,
        },
    )
    return [
        {
            "item_type": (r["item_type"] or "Unknown"),
            "total_seconds": int(r["total_seconds"] or 0),
            "plays": int(r["plays"] or 0),
        }
        for r in result.mappings().fetchall()
    ]


async def get_user_longest_session(
    session: AsyncSession,
    instance_id: int,
    user_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    """Single longest playback session for the user in the date range."""
    ld = _local_date_expr("s.start_time")
    result = await session.execute(
        text(
            f"""
            SELECT s.duration_seconds,
                   s.start_time,
                   COALESCE(i.name, 'Unknown') AS item_name,
                   COALESCE(i.type, 'Unknown') AS item_type
            FROM emby_playback_sessions s
            LEFT JOIN emby_items i
              ON i.instance_id = s.instance_id
              AND i.item_id = CAST(s.item_id AS TEXT)
            WHERE s.instance_id = :instance_id
              AND CAST(s.user_id AS TEXT) = :user_id
              AND {ld} BETWEEN :start_date AND :end_date
            ORDER BY s.duration_seconds DESC
            LIMIT 1
            """
        ),
        {
            "instance_id": instance_id,
            "user_id": str(user_id),
            "start_date": start_date,
            "end_date": end_date,
            "tz": TIMEZONE,
        },
    )
    row = result.mappings().fetchone()
    if not row:
        return None
    return {
        "duration_seconds": int(row["duration_seconds"] or 0),
        "start_time": row["start_time"],
        "item_name": row["item_name"],
        "item_type": row["item_type"],
    }


async def get_user_top_weekday(
    session: AsyncSession,
    instance_id: int,
    user_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    """Weekday with the highest average daily watch time (averaged over watched
    days only). PG DOW: 0=Sun..6=Sat."""
    ld = _local_date_expr("s.start_time")
    result = await session.execute(
        text(
            f"""
            WITH per_day AS (
                SELECT {ld} AS local_date,
                       EXTRACT(DOW FROM
                           (LEFT(s.start_time, 19)::timestamp
                                AT TIME ZONE 'UTC' AT TIME ZONE :tz)
                       )::int AS dow,
                       SUM(s.duration_seconds) AS day_total
                FROM emby_playback_sessions s
                WHERE s.instance_id = :instance_id
                  AND CAST(s.user_id AS TEXT) = :user_id
                  AND {ld} BETWEEN :start_date AND :end_date
                GROUP BY local_date, dow
            )
            SELECT dow,
                   AVG(day_total)::bigint AS avg_seconds,
                   SUM(day_total)::bigint AS total_seconds,
                   COUNT(*)::int AS days_count
            FROM per_day
            GROUP BY dow
            ORDER BY avg_seconds DESC
            LIMIT 1
            """
        ),
        {
            "instance_id": instance_id,
            "user_id": str(user_id),
            "start_date": start_date,
            "end_date": end_date,
            "tz": TIMEZONE,
        },
    )
    row = result.mappings().fetchone()
    if not row:
        return None
    names = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]
    dow = int(row["dow"])
    return {
        "dow": dow,
        "name": names[dow] if 0 <= dow < 7 else "Unknown",
        "avg_seconds": int(row["avg_seconds"] or 0),
        "total_seconds": int(row["total_seconds"] or 0),
        "days_count": int(row["days_count"] or 0),
    }


async def get_plays_per_user(
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
            FROM emby_metrics_snapshot_user
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


async def get_watch_time_per_user(
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
            FROM emby_metrics_snapshot_user s
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
            f"SELECT COUNT(DISTINCT (instance_id, user_id))"
            f" FROM emby_metrics_snapshot_user WHERE 1=1{dr}{inst_w}{usr_w}"
        ),
        params,
    )
    row = result.fetchone()
    return int(row[0]) if row else 0


# Public names for these two arrived late; the underscore aliases stay because
# metrics_activity, jellyfin_dashboard_metrics and plex_dashboard_metrics all
# import them by the old name.
_get_plays_per_user = get_plays_per_user
_get_watch_time_per_user = get_watch_time_per_user
