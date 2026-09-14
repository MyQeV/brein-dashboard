"""Append-only store for raw Plex PMS notification WebSocket payloads.

Plex emits a frame per second per active stream, so this table grows without
limit unless something trims it. Nothing derives state from it — the live poll
in `now_playing` is what builds sessions — it exists for diagnostics, so a
short retention is enough, and an unbounded one made `POST /api/database/backups`
(which loads every table into memory) fail outright on a busy server.
"""

import time

from sqlalchemy import text

from brein.db import get_session_factory

# Diagnostics only: a couple of days is plenty to inspect a problem.
RETENTION_DAYS = 3


async def append_event(
    instance_id: int,
    raw_payload: str,
    *,
    event_type: str | None = None,
) -> None:
    """Insert one WebSocket notification row."""
    received_at = time.time()
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO plex_ws_events"
                " (instance_id, received_at, event_type, raw_payload)"
                " VALUES (:instance_id, :received_at, :event_type, :raw_payload)"
            ),
            {
                "instance_id": instance_id,
                "received_at": received_at,
                "event_type": event_type,
                "raw_payload": raw_payload or "",
            },
        )
        await session.commit()


async def prune_events(retention_days: int = RETENTION_DAYS) -> int:
    """Delete frames older than the retention window. Returns rows removed."""
    cutoff = time.time() - retention_days * 86_400
    async with get_session_factory()() as session:
        result = await session.execute(
            text("DELETE FROM plex_ws_events WHERE received_at < :cutoff"),
            {"cutoff": cutoff},
        )
        await session.commit()
        return result.rowcount or 0
