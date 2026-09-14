"""Scheduled task administration (admin only).

Replaces the Jinja handlers that returned rendered table rows. The runner
reads ``scheduled_tasks.interval_seconds``, so this is the only place a task's
cadence is set — there is deliberately no equivalent under system settings.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from brein.db import get_session_factory
from brein.jobs import scheduled_task_runner
from brein.store import instances as store_instances
from brein.store import scheduled_tasks as store
from brein.web import auth as web_auth
from brein.web.schemas import User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]

# The runner polls every few seconds; anything under 5s would just queue up.
MIN_INTERVAL_SECONDS = 5
MAX_INTERVAL_SECONDS = 86400
RECENT_RUN_LIMIT = 50


class IntervalBody(BaseModel):
    interval_seconds: int = Field(ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS)


class EnabledBody(BaseModel):
    enabled: bool


async def _instance_labels() -> dict[int, str]:
    rows = await store_instances.list_instances()
    labels: dict[int, str] = {}
    for row in rows:
        try:
            labels[int(row["id"])] = row.get("label") or str(row["id"])
        except (TypeError, ValueError, KeyError):
            continue
    return labels


@router.get("")
async def list_tasks(_user: AdminUser) -> dict[str, Any]:
    """All scheduled tasks, flat.

    Returned unsorted-by-group on purpose: the Jinja handler grouped globals
    first and then per instance, which is a presentation decision the client
    can make from instance_id and instance_label.
    """
    async with get_session_factory()() as session:
        tasks = await store.list_all_for_ui(session)
    labels = await _instance_labels()
    running = scheduled_task_runner.running_task_ids()
    for task in tasks:
        instance_id = task.get("instance_id")
        task["instance_label"] = (
            labels.get(int(instance_id)) if instance_id is not None else None
        )
        task["is_running"] = int(task["id"]) in running
    return {"tasks": tasks}


@router.get("/{task_id}")
async def get_task_detail(task_id: int, _user: AdminUser) -> dict[str, Any]:
    """One task plus its recent runs."""
    async with get_session_factory()() as session:
        task = await store.get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        runs = await store.get_latest_runs(session, task_id, limit=RECENT_RUN_LIMIT)
    task["is_running"] = task_id in scheduled_task_runner.running_task_ids()
    return {"task": task, "runs": runs}


@router.post("/{task_id}/run")
async def run_task_now(task_id: int, _user: AdminUser) -> dict[str, Any]:
    """Make a task due immediately.

    Clears last_run_at rather than executing inline: the runner owns execution
    and its in-process guard is what stops a task running twice.
    """
    async with get_session_factory()() as session:
        if not await store.get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        # A task that is mid-run would swallow this: the runner skips ids it
        # is already running, and the in-flight run then writes its own
        # finish time over the cleared one — so the request was accepted and
        # nothing ever ran. Say so instead.
        if task_id in scheduled_task_runner.running_task_ids():
            raise HTTPException(
                status_code=409,
                detail="Task is already running; try again when it ends",
            )
        await store.clear_last_run(session, task_id)
        await session.commit()
    return {"ok": True}


@router.put("/{task_id}/enabled")
async def set_task_enabled(
    task_id: int, body: EnabledBody, _user: AdminUser
) -> dict[str, Any]:
    async with get_session_factory()() as session:
        if not await store.get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        await store.set_enabled(session, task_id, body.enabled)
        await session.commit()
        task = await store.get_task(session, task_id)
    return {"task": task}


@router.put("/{task_id}/interval")
async def set_task_interval(
    task_id: int, body: IntervalBody, _user: AdminUser
) -> dict[str, Any]:
    async with get_session_factory()() as session:
        if not await store.get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        await store.set_interval(session, task_id, body.interval_seconds)
        await session.commit()
        task = await store.get_task(session, task_id)
    return {"task": task}
