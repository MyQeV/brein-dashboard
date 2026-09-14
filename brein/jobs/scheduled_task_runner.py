"""Single-process polling scheduler.

One ``scheduled_task_runner_loop()`` coroutine wakes every POLL_SECONDS,
loads tasks whose next run is due, and spawns concurrent ``_execute`` coroutines
for each. Concurrency control is in-memory via ``_running_task_ids`` (the app
runs in a single container per CLAUDE.md).

Each ``_execute`` call:
  * opens a short bookkeeping session and creates a run row (status=running)
  * resolves the TaskType from the registry
  * invokes ``TaskType.execute(task, instance, session)`` inside a try/except
  * captures full traceback (truncated to 4000 chars) on error
  * updates the run row + the denormalized last_* columns on the task

Long-running task work should open its own scoped session — the bookkeeping
session is held only for create_run / finish_run / status updates.
"""

import asyncio
import logging

from brein import background
import time
import traceback
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory
from brein.jobs.scheduled_task_registry import get_task_type
from brein.store import plex_ws_events as store_plex_ws_events
from brein.store import scheduled_tasks as store

log = logging.getLogger(__name__)

POLL_SECONDS = 5
PRUNE_INTERVAL_SECONDS = 3600
PRUNE_RETENTION_DAYS = 14

_running_task_ids: set[int] = set()


def running_task_ids() -> set[int]:
    """Ids currently executing in this process.

    Public accessor so the API does not reach into the module global. Note it
    is per-process: with more than one worker this is only ever a partial
    view.
    """
    return set(_running_task_ids)


async def _load_task_with_instance(
    task_id: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Fetch the task row and its instance row (if any). One short-lived session."""
    async with get_session_factory()() as session:
        task = await store.get_task(session, task_id)
        if task is None:
            return None, None
        instance: dict[str, Any] | None = None
        if task["instance_id"] is not None:
            row = await session.execute(
                text(
                    "SELECT id, service_type, label, host, port, api_key, "
                    "external_url, active FROM app_instances WHERE id = :id"
                ),
                {"id": task["instance_id"]},
            )
            r = row.fetchone()
            if r is None or not r._mapping["active"]:
                return task, None
            instance = dict(r._mapping)
        return task, instance


async def _execute(task_id: int) -> None:
    """Run one task and persist its result. Errors here never bubble up."""
    if task_id in _running_task_ids:
        return
    _running_task_ids.add(task_id)
    run_id: int | None = None
    started = time.monotonic()
    try:
        task, instance = await _load_task_with_instance(task_id)
        if task is None:
            return
        # Skip if instance got deactivated between selection and execute.
        if task["instance_id"] is not None and instance is None:
            return

        tt = get_task_type(task["key"])
        if tt is None:
            log.warning("scheduler: unknown task key %r (id=%s)", task["key"], task_id)
            async with get_session_factory()() as s:
                run_id = await store.create_run(s, task_id)
                await store.finish_run(
                    s,
                    run_id,
                    status="error",
                    error_message=f"unknown task key: {task['key']}",
                    duration_ms=0,
                )
                await store.update_task_last_run(
                    s, task_id, status="error", duration_ms=0
                )
                await s.commit()
            return

        async with get_session_factory()() as s:
            run_id = await store.create_run(s, task_id)
            await s.commit()

        # Execute outside the bookkeeping session so long work doesn't hold a tx.
        try:
            async with get_session_factory()() as work_session:
                await tt.execute(task, instance, work_session)
                await work_session.commit()
            duration_ms = int((time.monotonic() - started) * 1000)
            async with get_session_factory()() as s:
                await store.finish_run(
                    s, run_id, status="success", duration_ms=duration_ms
                )
                await store.update_task_last_run(
                    s, task_id, status="success", duration_ms=duration_ms
                )
                await s.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            tb = traceback.format_exc()
            duration_ms = int((time.monotonic() - started) * 1000)
            log.warning(
                "scheduler: task %s (%s) failed: %s",
                task_id,
                task["key"],
                tb.splitlines()[-1] if tb else "",
            )
            try:
                async with get_session_factory()() as s:
                    await store.finish_run(
                        s,
                        run_id,
                        status="error",
                        error_message=tb,
                        duration_ms=duration_ms,
                    )
                    await store.update_task_last_run(
                        s, task_id, status="error", duration_ms=duration_ms
                    )
                    await s.commit()
            except Exception as inner:
                log.error("scheduler: failed to record error row: %s", inner)
    except asyncio.CancelledError:
        raise
    except Exception as outer:
        log.error("scheduler: outer _execute failure for task %s: %s", task_id, outer)
    finally:
        _running_task_ids.discard(task_id)


async def _prune_loop_pass() -> None:
    try:
        async with get_session_factory()() as s:
            removed = await store.prune_runs(s, PRUNE_RETENTION_DAYS)
            await s.commit()
            if removed:
                log.info("scheduler: pruned %d old run rows", removed)
    except Exception as exc:
        log.warning("scheduler: prune failed: %s", exc)

    # Raw Plex notification frames: one per second per stream, read by nothing,
    # and loaded whole into memory by the database backup.
    try:
        removed = await store_plex_ws_events.prune_events()
        if removed:
            log.info("scheduler: pruned %d old Plex WebSocket frames", removed)
    except Exception as exc:
        log.warning("scheduler: Plex frame prune failed: %s", exc)


async def scheduled_task_runner_loop() -> None:
    """Main loop. Cancels cleanly on asyncio cancellation."""
    log.info("scheduled task runner started (poll=%ds)", POLL_SECONDS)
    # Due immediately: keyed to uptime, a container restarted more often than
    # the prune interval never pruned at all, and run history grew unbounded.
    last_prune = time.monotonic() - PRUNE_INTERVAL_SECONDS
    try:
        while True:
            try:
                async with get_session_factory()() as s:
                    due = await store.list_due_enabled(s)
                for row in due:
                    if row["id"] in _running_task_ids:
                        continue
                    background.spawn(
                        _execute(int(row["id"])), f"scheduled_task[{row['id']}]"
                    )
                if time.monotonic() - last_prune >= PRUNE_INTERVAL_SECONDS:
                    await _prune_loop_pass()
                    last_prune = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("scheduler tick error: %s", exc)
            await asyncio.sleep(POLL_SECONDS)
    except asyncio.CancelledError:
        log.info("scheduled task runner cancelled")
        raise
