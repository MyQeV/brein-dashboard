"""Scheduled-task persistence: tasks catalog + run history.

Functions accept an open AsyncSession; callers manage session lifecycle and
commit timing. This matches the runner's need to atomically finish a run row
and update the task's denormalized last_* columns in one transaction.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

_ERROR_MAX_LEN = 4000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def list_due_enabled(session: AsyncSession) -> list[dict[str, Any]]:
    """Return tasks that are enabled and due to run.

    A task is due when last_run_at IS NULL or last_run_at + interval_seconds <= now().
    Instance-bound tasks are skipped if their instance is inactive.
    """
    sql = text(
        """
        SELECT t.id, t.key, t.name, t.instance_id, t.interval_seconds, t.category
        FROM scheduled_tasks t
        LEFT JOIN app_instances i ON i.id = t.instance_id
        WHERE t.enabled = TRUE
          AND (t.instance_id IS NULL OR i.active = TRUE)
          AND (
            t.last_run_at IS NULL
            OR t.last_run_at + (t.interval_seconds || ' seconds')::interval <= NOW()
          )
        ORDER BY t.last_run_at NULLS FIRST
        """
    )
    result = await session.execute(sql)
    return [dict(row._mapping) for row in result.fetchall()]


async def get_task(session: AsyncSession, task_id: int) -> dict[str, Any] | None:
    sql = text(
        """
        SELECT id, key, name, instance_id, interval_seconds, enabled, category,
               config_json, last_run_at, last_status, last_duration_ms,
               created_at, updated_at
        FROM scheduled_tasks WHERE id = :id
        """
    )
    row = (await session.execute(sql, {"id": task_id})).fetchone()
    return dict(row._mapping) if row else None


async def list_all_for_ui(
    session: AsyncSession,
    *,
    category: str | None = None,
    enabled: bool | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    """List all tasks for the UI grouped page (no pagination — count is small)."""
    where: list[str] = []
    params: dict[str, Any] = {}
    if category:
        where.append("t.category = :category")
        params["category"] = category
    if enabled is not None:
        where.append("t.enabled = :enabled")
        params["enabled"] = enabled
    if q:
        where.append("(t.name ILIKE :q OR t.key ILIKE :q)")
        params["q"] = f"%{q}%"
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = text(
        f"""
        SELECT t.id, t.key, t.name, t.instance_id, t.interval_seconds, t.enabled,
               t.category, t.last_run_at, t.last_status, t.last_duration_ms,
               i.label AS instance_label, i.service_type AS instance_service_type,
               i.active AS instance_active
        FROM scheduled_tasks t
        LEFT JOIN app_instances i ON i.id = t.instance_id
        {where_sql}
        ORDER BY (t.instance_id IS NOT NULL), i.sort_order NULLS FIRST, i.label,
                 t.category, t.name
        """
    )
    result = await session.execute(sql, params)
    return [dict(row._mapping) for row in result.fetchall()]


async def upsert_task(
    session: AsyncSession,
    *,
    key: str,
    name: str,
    instance_id: int | None,
    interval_seconds: int,
    category: str,
    last_run_at: datetime | None = None,
) -> None:
    """Insert task if it doesn't exist; otherwise leave user-edited fields intact.

    On insert: seeds last_run_at to caller-supplied value (used to stagger).
    On conflict: updates only the static `name` and `category` (registry-driven).
    """
    sql = text(
        """
        INSERT INTO scheduled_tasks (key, name, instance_id, interval_seconds,
                                     enabled, category, config_json, last_run_at)
        VALUES (:key, :name, :instance_id, :interval_seconds, TRUE, :category,
                '{}', :last_run_at)
        ON CONFLICT (key, instance_id) DO UPDATE
            SET name = EXCLUDED.name,
                category = EXCLUDED.category,
                updated_at = NOW()
        """
    )
    await session.execute(
        sql,
        {
            "key": key,
            "name": name,
            "instance_id": instance_id,
            "interval_seconds": interval_seconds,
            "category": category,
            "last_run_at": last_run_at,
        },
    )


async def delete_unknown_keys(session: AsyncSession, known_keys: list[str]) -> int:
    if not known_keys:
        return 0
    sql = text("DELETE FROM scheduled_tasks WHERE key NOT IN :keys").bindparams(
        bindparam("keys", expanding=True)
    )
    result = await session.execute(sql, {"keys": list(known_keys)})
    return result.rowcount or 0


async def create_run(session: AsyncSession, task_id: int) -> int:
    sql = text(
        """
        INSERT INTO scheduled_task_runs (task_id, started_at, status)
        VALUES (:task_id, NOW(), 'running')
        RETURNING id
        """
    )
    row = (await session.execute(sql, {"task_id": task_id})).fetchone()
    if row is None:
        raise RuntimeError("create_run: INSERT did not return an id")
    return int(row[0])


async def finish_run(
    session: AsyncSession,
    run_id: int,
    *,
    status: str,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    msg = error_message[:_ERROR_MAX_LEN] if error_message else None
    sql = text(
        """
        UPDATE scheduled_task_runs
        SET status = :status,
            finished_at = NOW(),
            error_message = :msg,
            duration_ms = :duration_ms
        WHERE id = :id
        """
    )
    await session.execute(
        sql,
        {"id": run_id, "status": status, "msg": msg, "duration_ms": duration_ms},
    )


async def update_task_last_run(
    session: AsyncSession,
    task_id: int,
    *,
    status: str,
    duration_ms: int | None,
) -> None:
    sql = text(
        """
        UPDATE scheduled_tasks
        SET last_run_at = NOW(),
            last_status = :status,
            last_duration_ms = :duration_ms,
            updated_at = NOW()
        WHERE id = :id
        """
    )
    await session.execute(
        sql, {"id": task_id, "status": status, "duration_ms": duration_ms}
    )


async def reap_orphan_running_runs(session: AsyncSession) -> int:
    """Mark any runs left in 'running' state (from a prior crash) as errored."""
    sql = text(
        """
        UPDATE scheduled_task_runs
        SET status = 'error',
            finished_at = NOW(),
            error_message = 'orphaned (process restart)'
        WHERE status = 'running'
        """
    )
    result = await session.execute(sql)
    return result.rowcount or 0


async def get_latest_runs(
    session: AsyncSession, task_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT id, started_at, finished_at, status, error_message, duration_ms
        FROM scheduled_task_runs
        WHERE task_id = :task_id
        ORDER BY started_at DESC
        LIMIT :limit
        """
    )
    result = await session.execute(sql, {"task_id": task_id, "limit": limit})
    return [dict(row._mapping) for row in result.fetchall()]


async def prune_runs(session: AsyncSession, retention_days: int = 14) -> int:
    # `:days || ' days'` binds the parameter as text concatenation, and asyncpg
    # refuses an int where the query implies str — so this raised DataError on
    # every call. Multiplying a fixed interval keeps the value numeric.
    sql = text(
        """
        DELETE FROM scheduled_task_runs
        WHERE started_at < NOW() - (:days * INTERVAL '1 day')
        """
    )
    result = await session.execute(sql, {"days": int(retention_days)})
    return result.rowcount or 0


async def set_enabled(session: AsyncSession, task_id: int, enabled: bool) -> None:
    await session.execute(
        text(
            "UPDATE scheduled_tasks SET enabled = :enabled, updated_at = NOW()"
            " WHERE id = :id"
        ),
        {"id": task_id, "enabled": enabled},
    )


async def set_interval(
    session: AsyncSession, task_id: int, interval_seconds: int
) -> None:
    if interval_seconds < 5:
        raise ValueError("interval_seconds must be >= 5")
    await session.execute(
        text(
            "UPDATE scheduled_tasks SET interval_seconds = :sec, updated_at = NOW()"
            " WHERE id = :id"
        ),
        {"id": task_id, "sec": interval_seconds},
    )


async def clear_last_run(session: AsyncSession, task_id: int) -> None:
    """Set last_run_at = NULL so the runner picks up the task on next tick."""
    await session.execute(
        text(
            "UPDATE scheduled_tasks SET last_run_at = NULL, updated_at = NOW()"
            " WHERE id = :id"
        ),
        {"id": task_id},
    )


async def state_summary(session: AsyncSession) -> list[dict[str, Any]]:
    """Lightweight payload for HTMX polling: per task last_run_at + status."""
    sql = text(
        """
        SELECT id, last_run_at, last_status, last_duration_ms,
               last_run_at + (interval_seconds || ' seconds')::interval AS next_due_at
        FROM scheduled_tasks
        """
    )
    result = await session.execute(sql)
    return [dict(row._mapping) for row in result.fetchall()]
