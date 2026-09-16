"""Retired store for raw Plex PMS notification WebSocket payloads.

Plex emits a frame per second per active stream, and every one was an INSERT
and a COMMIT of its own. Nothing reads the table — the live poll in
`now_playing` is what builds sessions, and no query, export or page selects
from it — so the frames are no longer stored at all. The `PlexWsEvent` model
stays so `create_all` and the instance-cascade repair are unchanged, and
`prune_events` keeps draining whatever an older build left behind.
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
    """Discard one WebSocket notification. Kept so the listener needs no change."""
    return None


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
