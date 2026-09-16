"""Build and store emby_playback_sessions from emby_activity_log_entries."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory

log = logging.getLogger(__name__)

MAX_DURATION_SECONDS = 8 * 3600

PLAYBACK_START_TYPES = frozenset(("playback.start", "VideoPlayback"))
PLAYBACK_STOP_TYPES = frozenset(("playback.stop", "VideoPlaybackStopped"))
_ALL_PLAYBACK_TYPES = tuple(PLAYBACK_START_TYPES | PLAYBACK_STOP_TYPES)
# Safe to embed as string literals since these are internal constants, not user input.
_SQL_TYPES_LITERAL = "(" + ",".join(f"'{t}'" for t in _ALL_PLAYBACK_TYPES) + ")"


async def get_last_processed_entry_id(instance_id: int) -> int | None:
    """Return last_entry_id from emby_playback_sessions_state for this instance, or None."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT last_entry_id FROM emby_playback_sessions_state"
                " WHERE instance_id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = result.fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return None


async def set_last_processed_entry_id(instance_id: int, entry_id: int) -> None:
    """Upsert last_entry_id for this instance into emby_playback_sessions_state."""
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO emby_playback_sessions_state (instance_id, last_entry_id)"
                " VALUES (:instance_id, :entry_id)"
                " ON CONFLICT (instance_id) DO UPDATE SET last_entry_id = EXCLUDED.last_entry_id"
            ),
            {"instance_id": instance_id, "entry_id": entry_id},
        )
        await session.commit()


def _parse_dt(date: str) -> datetime:
    """Parse an ISO 8601 date string to an aware UTC datetime.

    A value without an offset is taken as UTC: subtracting a naive datetime
    from an aware one raises TypeError, and one entry with a 'Z' next to one
    without threw the whole group away.
    """
    parsed = datetime.fromisoformat(date)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_sessions_from_events(
    events: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    """Walk chronologically-sorted events and produce session rows via state machine.

    Each event tuple is (instance_id, user_id, item_id, type, date).
    Returns list of dicts for emby_playback_sessions INSERT.
    """
    sessions: list[dict[str, Any]] = []
    current_group: tuple[Any, ...] | None = None
    session_start_date: str | None = None

    for iid, uid, item, event_type, date in events:
        group = (iid, uid, item)
        if group != current_group:
            current_group = group
            session_start_date = None
        if event_type in PLAYBACK_START_TYPES:
            if session_start_date is None:
                session_start_date = date
        elif session_start_date is not None:
            try:
                duration = int(
                    (_parse_dt(date) - _parse_dt(session_start_date)).total_seconds()
                )
            except (TypeError, ValueError):
                session_start_date = None
                continue
            if 0 < duration <= MAX_DURATION_SECONDS:
                sessions.append(
                    {
                        "instance_id": iid,
                        "user_id": uid,
                        "item_id": item,
                        "start_time": session_start_date,
                        "end_time": date,
                        "duration_seconds": duration,
                    }
                )
            session_start_date = None

    return sessions


async def rebuild_sessions(
    instance_id: int | None = None,
    since_date: str | None = None,
) -> int:
    """Rebuild emby_playback_sessions from activity log using a state-machine.

    When ``since_date`` is provided, only (user_id, item_id) groups that have
    activity at or after that date are rebuilt. Returns the number of sessions inserted.
    """
    async with get_session_factory()() as session:
        inst_filter = (
            " AND instance_id = :instance_id" if instance_id is not None else ""
        )
        # The joined fetch below carries the column on both sides.
        e_inst_filter = (
            " AND e.instance_id = :instance_id" if instance_id is not None else ""
        )
        inst_params: dict[str, Any] = (
            {"instance_id": instance_id} if instance_id is not None else {}
        )

        if since_date:
            affected_result = await session.execute(
                text(
                    f"""
                    SELECT DISTINCT instance_id, user_id, item_id
                    FROM emby_activity_log_entries
                    WHERE type IN {_SQL_TYPES_LITERAL}
                      AND item_id IS NOT NULL AND user_id IS NOT NULL
                      AND date >= :since_date
                      {inst_filter}
                    """
                ),
                {"since_date": since_date, **inst_params},
            )
            affected_groups = affected_result.fetchall()

            if not affected_groups:
                return 0

            await session.execute(
                text(
                    "CREATE TEMP TABLE IF NOT EXISTS _rebuild_groups"
                    " (instance_id INTEGER, user_id INTEGER, item_id INTEGER)"
                )
            )
            await session.execute(text("DELETE FROM _rebuild_groups"))
            await session.execute(
                text(
                    "INSERT INTO _rebuild_groups (instance_id, user_id, item_id)"
                    " VALUES (:iid, :uid, :item)"
                ),
                [{"iid": g[0], "uid": g[1], "item": g[2]} for g in affected_groups],
            )

            # One statement for every group, not one round trip each: with a
            # thousand groups touched in a minute that was a thousand DELETEs,
            # every one a scan of the instance's sessions before the
            # (instance_id, user_id, item_id) index existed.
            await session.execute(
                text(
                    "DELETE FROM emby_playback_sessions s"
                    " USING _rebuild_groups g"
                    " WHERE s.instance_id = g.instance_id"
                    "   AND s.user_id = g.user_id"
                    "   AND s.item_id = g.item_id"
                )
            )

            fetch_result = await session.execute(
                text(
                    f"""
                    SELECT e.instance_id, e.user_id, e.item_id, e.type, e.date
                    FROM emby_activity_log_entries e
                    INNER JOIN _rebuild_groups g
                        ON g.instance_id = e.instance_id
                       AND g.user_id = e.user_id
                       AND g.item_id = e.item_id
                    WHERE e.type IN {_SQL_TYPES_LITERAL}
                      AND e.item_id IS NOT NULL AND e.user_id IS NOT NULL
                      {e_inst_filter}
                    ORDER BY e.instance_id, e.user_id, e.item_id, e.date ASC
                    """
                ),
                inst_params,
            )
            rows = fetch_result.fetchall()
            await session.execute(text("DROP TABLE IF EXISTS _rebuild_groups"))
        else:
            del_sql = "DELETE FROM emby_playback_sessions"
            if instance_id is not None:
                del_sql += " WHERE instance_id = :instance_id"
            await session.execute(text(del_sql), inst_params)

            fetch_result = await session.execute(
                text(
                    f"""
                    SELECT instance_id, user_id, item_id, type, date
                    FROM emby_activity_log_entries
                    WHERE type IN {_SQL_TYPES_LITERAL}
                      AND item_id IS NOT NULL AND user_id IS NOT NULL
                      {inst_filter}
                    ORDER BY instance_id, user_id, item_id, date ASC
                    """
                ),
                inst_params,
            )
            rows = fetch_result.fetchall()

        sessions = _build_sessions_from_events(rows)
        if sessions:
            await session.execute(
                text(
                    "INSERT INTO emby_playback_sessions"
                    " (instance_id, user_id, item_id, start_time, end_time, duration_seconds)"
                    " VALUES (:instance_id, :user_id, :item_id, :start_time, :end_time,"
                    "  :duration_seconds)"
                ),
                sessions,
            )

        await session.commit()
        return len(sessions)


async def reset_all_sessions() -> None:
    """Delete all rows from emby_playback_sessions and emby_playback_sessions_state."""
    async with get_session_factory()() as session:
        await session.execute(text("DELETE FROM emby_playback_sessions"))
        await session.execute(text("DELETE FROM emby_playback_sessions_state"))
        await session.commit()
