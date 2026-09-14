"""The DB-driven scheduler's own rules, against real rows.

The runner is a five-second poll over one query, so almost everything that can
go wrong is in that query or in the bookkeeping around it — and both have.
Run-history pruning was scheduled off process uptime, so a container restarted
more often than the hourly interval never pruned at all, which hid that the
delete raised on every call. Nothing failed loudly: the loop logs and carries
on, and the table grew for months.

These cover what the scheduler promises: which tasks come back due, that a
paused instance stops its tasks without a separate column, that reconcile is
idempotent over user edits, and that the two maintenance statements do what
they say.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from brein.jobs import scheduled_task_reconciler as reconciler
from brein.jobs.scheduled_task_registry import task_types
from brein.store import scheduled_tasks as store
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio(loop_scope="session"), requires_db]

# Clear of the ids the other database-backed tests use.
INSTANCE = 92_001

# A key no registry entry uses, so these rows are only ever this test's.
TEST_KEY = "pytest_scheduler_probe"


def _ago(**kwargs) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kwargs)


async def _reset(session) -> None:
    await session.execute(
        text(
            "DELETE FROM scheduled_task_runs WHERE task_id IN"
            " (SELECT id FROM scheduled_tasks WHERE key = :key"
            "  OR instance_id = :instance)"
        ),
        {"key": TEST_KEY, "instance": INSTANCE},
    )
    await session.execute(
        text("DELETE FROM scheduled_tasks WHERE key = :key OR instance_id = :instance"),
        {"key": TEST_KEY, "instance": INSTANCE},
    )
    await session.execute(
        text("DELETE FROM app_instances WHERE id = :id"), {"id": INSTANCE}
    )
    await session.commit()


async def _instance(session, *, active: bool = True) -> None:
    await session.execute(
        text(
            "INSERT INTO app_instances"
            " (id, service_type, label, host, api_key, external_url,"
            "  active, sort_order)"
            " VALUES (:id, 'emby', 'Probe', 'http://localhost', '', '',"
            "  :active, 0)"
        ),
        {"id": INSTANCE, "active": active},
    )
    await session.commit()


async def _task(
    session,
    *,
    instance_id: int | None = None,
    interval_seconds: int = 60,
    enabled: bool = True,
    last_run_at: datetime | None = None,
) -> int:
    row = await session.execute(
        text(
            "INSERT INTO scheduled_tasks"
            " (key, name, instance_id, interval_seconds, enabled, category,"
            "  config_json, last_run_at)"
            " VALUES (:key, 'Probe', :instance_id, :interval, :enabled,"
            "  'sync', '{}', :last_run_at)"
            " RETURNING id"
        ),
        {
            "key": TEST_KEY,
            "instance_id": instance_id,
            "interval": interval_seconds,
            "enabled": enabled,
            "last_run_at": last_run_at,
        },
    )
    task_id = int(row.scalar_one())
    await session.commit()
    return task_id


async def _due_ids(session) -> set[int]:
    return {int(row["id"]) for row in await store.list_due_enabled(session)}


class TestDueSelection:
    async def test_a_task_that_never_ran_is_due(self, session):
        await _reset(session)
        task_id = await _task(session, last_run_at=None)
        assert task_id in await _due_ids(session)

    async def test_a_task_inside_its_interval_is_not_due(self, session):
        await _reset(session)
        task_id = await _task(
            session, interval_seconds=3600, last_run_at=_ago(minutes=5)
        )
        assert task_id not in await _due_ids(session)

    async def test_a_task_past_its_interval_is_due(self, session):
        await _reset(session)
        task_id = await _task(session, interval_seconds=3600, last_run_at=_ago(hours=2))
        assert task_id in await _due_ids(session)

    async def test_a_disabled_task_is_never_due(self, session):
        await _reset(session)
        task_id = await _task(session, enabled=False, last_run_at=None)
        assert task_id not in await _due_ids(session)

    async def test_an_inactive_instance_pauses_its_tasks(self, session):
        """The pause rule, which has no column of its own.

        Deactivating a server must stop its syncs. The runner reads that off
        app_instances.active through the join — there is no `paused` flag to
        forget to set.
        """
        await _reset(session)
        await _instance(session, active=False)
        task_id = await _task(session, instance_id=INSTANCE, last_run_at=None)
        assert task_id not in await _due_ids(session)

    async def test_an_active_instance_does_not(self, session):
        await _reset(session)
        await _instance(session, active=True)
        task_id = await _task(session, instance_id=INSTANCE, last_run_at=None)
        assert task_id in await _due_ids(session)

    async def test_a_global_task_ignores_instance_state(self, session):
        """instance_id IS NULL must survive the LEFT JOIN's null row.

        An inner join here, or a bare `i.active = TRUE`, silently drops every
        global task — the cache refresh, the token cleanup, the broadcast.
        """
        await _reset(session)
        await _instance(session, active=False)
        task_id = await _task(session, instance_id=None, last_run_at=None)
        assert task_id in await _due_ids(session)


class TestRunBookkeeping:
    async def test_prune_removes_only_old_runs(self, session):
        """The statement that raised on every call for months.

        Binding an int into `:days || ' days'` makes asyncpg reject the
        parameter, and the loop logs the failure and continues — so the only
        evidence was a table that never shrank.
        """
        await _reset(session)
        task_id = await _task(session)

        run_id = await store.create_run(session, task_id)
        await store.finish_run(session, run_id, status="success", duration_ms=1)
        await session.execute(
            text("UPDATE scheduled_task_runs SET started_at = :old WHERE id = :id"),
            {"old": _ago(days=30), "id": run_id},
        )
        fresh_id = await store.create_run(session, task_id)
        await session.commit()

        removed = await store.prune_runs(session, retention_days=14)
        await session.commit()

        assert removed >= 1
        remaining = {
            int(row["id"]) for row in await store.get_latest_runs(session, task_id)
        }
        assert run_id not in remaining
        assert fresh_id in remaining

    async def test_orphaned_runs_are_reaped(self, session):
        """A crash leaves a run row saying 'running' forever."""
        await _reset(session)
        task_id = await _task(session)
        run_id = await store.create_run(session, task_id)
        await session.commit()

        await store.reap_orphan_running_runs(session)
        await session.commit()

        runs = {int(r["id"]): r for r in await store.get_latest_runs(session, task_id)}
        assert runs[run_id]["status"] == "error"
        assert runs[run_id]["finished_at"] is not None

    async def test_finishing_a_run_records_the_task_state(self, session):
        await _reset(session)
        task_id = await _task(session, last_run_at=None)
        run_id = await store.create_run(session, task_id)
        await store.finish_run(session, run_id, status="success", duration_ms=42)
        await store.update_task_last_run(
            session, task_id, status="success", duration_ms=42
        )
        await session.commit()

        task = await store.get_task(session, task_id)
        assert task is not None
        assert task["last_status"] == "success"
        assert task["last_duration_ms"] == 42
        # And the task is no longer due, which is what stops the runner from
        # spawning it again on the very next five-second tick.
        assert task_id not in await _due_ids(session)


class TestReconcile:
    async def test_seeds_one_row_per_instance_task_type(self, session):
        await _reset(session)
        await _instance(session)
        await reconciler.reconcile(session)

        rows = await session.execute(
            text("SELECT key FROM scheduled_tasks WHERE instance_id = :id"),
            {"id": INSTANCE},
        )
        seeded = {row[0] for row in rows.fetchall()}
        expected = {tt.key for tt in task_types().values() if tt.service_type == "emby"}
        assert expected
        assert seeded == expected

    async def test_preserves_user_edits_on_a_second_pass(self, session):
        """Reconcile runs on every boot and after every instance write.

        Refreshing interval_seconds or enabled from the registry would undo
        the settings page on the next restart.
        """
        await _reset(session)
        await _instance(session)
        await reconciler.reconcile(session)

        row = await session.execute(
            text("SELECT id FROM scheduled_tasks WHERE instance_id = :id LIMIT 1"),
            {"id": INSTANCE},
        )
        task_id = int(row.scalar_one())
        await store.set_interval(session, task_id, 999)
        await store.set_enabled(session, task_id, False)
        await session.commit()

        await reconciler.reconcile(session)

        task = await store.get_task(session, task_id)
        assert task is not None
        assert task["interval_seconds"] == 999
        assert task["enabled"] is False

    async def test_drops_rows_whose_key_left_the_registry(self, session):
        await _reset(session)
        await _task(session)  # TEST_KEY is in no registry entry.
        await reconciler.reconcile(session)

        row = await session.execute(
            text("SELECT COUNT(*) FROM scheduled_tasks WHERE key = :key"),
            {"key": TEST_KEY},
        )
        assert int(row.scalar_one()) == 0
