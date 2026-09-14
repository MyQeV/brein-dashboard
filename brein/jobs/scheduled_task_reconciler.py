"""Keep ``scheduled_tasks`` rows in sync with the code-side task_types() registry
and the live ``app_instances`` table.

Called once at startup (after schema create_all) and again whenever an instance
is created/updated/deleted. Existing user edits to ``interval_seconds`` and
``enabled`` are preserved by the upsert.

Initial ``last_run_at`` is staggered randomly within the task's interval so the
first batch of runs after a fresh boot doesn't all fire on the same tick.
"""

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brein.jobs.scheduled_task_registry import TaskType, task_types
from brein.store import scheduled_tasks as store

log = logging.getLogger(__name__)


def _initial_last_run(tt: TaskType) -> datetime:
    """Return a staggered last_run_at so freshly-seeded tasks don't all run at once."""
    jitter = random.randint(0, max(0, tt.default_interval_seconds - 1))
    return datetime.now(timezone.utc) - timedelta(
        seconds=tt.default_interval_seconds - jitter
    )


async def _list_active_instances(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.execute(
        text("SELECT id, service_type, label FROM app_instances ORDER BY id")
    )
    return [dict(r._mapping) for r in rows.fetchall()]


async def reconcile(session: AsyncSession) -> None:
    """Idempotent: ensure one row per (task_type, instance) pair.

    - For each global TaskType: upsert one row with ``instance_id IS NULL``.
    - For each AppInstance: upsert one row per matching TaskType.
    - Removes rows whose ``key`` is no longer in the registry (defensive).

    Existing rows keep their user-set ``interval_seconds`` and ``enabled``;
    only ``name``/``category`` are refreshed from the registry.
    """
    instances = await _list_active_instances(session)

    for tt in task_types().values():
        if tt.service_type is None:
            await store.upsert_task(
                session,
                key=tt.key,
                name=tt.name,
                instance_id=None,
                interval_seconds=tt.default_interval_seconds,
                category=tt.category,
                last_run_at=_initial_last_run(tt),
            )
        else:
            for inst in instances:
                if inst["service_type"] != tt.service_type:
                    continue
                await store.upsert_task(
                    session,
                    key=tt.key,
                    name=f"{tt.name} — {inst['label']}",
                    instance_id=int(inst["id"]),
                    interval_seconds=tt.default_interval_seconds,
                    category=tt.category,
                    last_run_at=_initial_last_run(tt),
                )

    removed = await store.delete_unknown_keys(session, list(task_types().keys()))
    if removed:
        log.info("scheduler reconcile: removed %d unknown-key tasks", removed)

    await session.commit()
