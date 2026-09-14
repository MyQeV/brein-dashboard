"""Deleting an instance must take its synced data with it.

Before this, `delete_instance` removed one row and 28 tables carrying a NOT
NULL `instance_id` had no foreign key at all, so every removed instance left
its users, items, playback sessions, metrics snapshots and activity log behind
forever — reachable by nothing, and able to resurface under a recycled serial
id. A 29th, sabnzbd_server_stats_snapshots, had a NO ACTION foreign key, which
did not orphan rows but made deleting a SABnzbd instance fail outright.
"""

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel

from brein.db import INSTANCE_ID_INDEX_TABLES, INSTANCE_SCOPED_TABLES
from brein.models import tables as _tables  # noqa: F401 — registers metadata
from tests.conftest import requires_db

# The `session` fixture is session-scoped, so its tests must share that loop.
# Without this they get a fresh function-scoped loop and every await on a
# connection opened by the fixture fails with "Event loop is closed".
pytestmark = pytest.mark.asyncio(loop_scope="session")

# Login accounts, not synced data: cascading these would delete Brein users,
# possibly admins. web.auth already denies login when the instance is gone.
EXEMPT_COLUMNS = {"emby_instance_id", "jellyfin_instance_id"}


def _cascade_fks(table) -> list:
    return [
        fk
        for column in table.columns
        if column.name == "instance_id"
        for fk in column.foreign_keys
        if fk.column.table.name == "app_instances"
    ]


def test_every_instance_scoped_table_cascades():
    """The guard that actually runs on every CI pass: no database needed.

    A new instance-scoped table must declare
    `foreign_key="app_instances.id", ondelete="CASCADE"` or deleting an
    instance will orphan its rows forever.
    """
    offenders = []
    for name, table in SQLModel.metadata.tables.items():
        if "instance_id" not in table.columns:
            continue
        fks = _cascade_fks(table)
        if len(fks) != 1 or fks[0].ondelete != "CASCADE":
            offenders.append(name)
    assert offenders == [], (
        f"missing ON DELETE CASCADE to app_instances: {offenders}. "
        'Declare foreign_key="app_instances.id", ondelete="CASCADE" on instance_id.'
    )


def test_the_scoped_table_list_matches_the_models():
    """db.INSTANCE_SCOPED_TABLES drives the migration; it must not drift."""
    from_models = {
        name
        for name, table in SQLModel.metadata.tables.items()
        if "instance_id" in table.columns and name != "scheduled_tasks"
    }
    assert from_models == set(INSTANCE_SCOPED_TABLES)


def test_users_table_is_not_cascaded():
    """Deleting an instance must never delete a login account."""
    users = SQLModel.metadata.tables["users"]
    for column_name in EXEMPT_COLUMNS:
        column = users.columns[column_name]
        assert not list(column.foreign_keys), (
            f"users.{column_name} must not reference app_instances: cascading it "
            "would delete Brein accounts, and SET NULL would silently convert a "
            "passthrough account into a local one."
        )


def test_index_list_covers_tables_whose_pk_does_not_lead_with_instance_id():
    """Without these, each cascaded delete sequentially scans the table."""
    for name in INSTANCE_ID_INDEX_TABLES:
        table = SQLModel.metadata.tables[name]
        pk_columns = [c.name for c in table.primary_key.columns]
        assert (
            pk_columns[0] != "instance_id"
        ), f"{name} already leads its PK with instance_id; it needs no extra index"
        assert any(
            list(index.columns)[0].name == "instance_id" for index in table.indexes
        ), f"{name} needs an index leading with instance_id"


# ── Database-backed ──────────────────────────────────────────────────────────


@requires_db
async def test_live_schema_has_validated_cascades(session):
    """Catches model/DDL divergence and a half-applied upgrade."""
    from sqlalchemy import text

    result = await session.execute(
        text(
            """
            SELECT c.conrelid::regclass::text AS tbl, c.confdeltype, c.convalidated
            FROM pg_constraint c
            WHERE c.contype = 'f' AND c.confrelid = 'app_instances'::regclass
            """
        )
    )

    # asyncpg returns Postgres' "char" type as bytes, not str.
    def _delete_rule(value: object) -> str:
        return value.decode() if isinstance(value, bytes) else str(value)

    live = {
        row.tbl: (_delete_rule(row.confdeltype), row.convalidated) for row in result
    }
    missing = [t for t in INSTANCE_SCOPED_TABLES if t not in live]
    wrong = [t for t, (d, v) in live.items() if d != "c" or not v]
    assert missing == [], f"no FK to app_instances: {missing}"
    assert wrong == [], f"FK is not a validated CASCADE: {wrong}"


@requires_db
async def test_delete_instance_cascades_and_is_scoped(session):
    """The cascade must remove the target's rows and leave other instances alone."""
    from sqlalchemy import text

    from brein.store import instances as store_instances

    doomed = await store_instances.create_instance("emby", label="cascade-doomed")
    survivor = await store_instances.create_instance("emby", label="cascade-survivor")
    try:
        for instance_id in (doomed, survivor):
            await session.execute(
                text(
                    "INSERT INTO emby_activity_log_entries"
                    " (instance_id, entry_id, name, type, date)"
                    " VALUES (:i, 1, 'seed', 'Seed', '2026-01-01T00:00:00Z')"
                ),
                {"i": instance_id},
            )
        await session.commit()

        assert await store_instances.delete_instance(doomed) is True

        result = await session.execute(
            text(
                "SELECT instance_id FROM emby_activity_log_entries"
                " WHERE instance_id IN (:a, :b)"
            ),
            {"a": doomed, "b": survivor},
        )
        remaining = [row.instance_id for row in result]
        assert (
            doomed not in remaining
        ), "cascade did not remove the deleted instance's rows"
        assert survivor in remaining, "cascade removed another instance's rows"
    finally:
        await store_instances.delete_instance(survivor)


@requires_db
async def test_deleting_a_sabnzbd_instance_with_stats_does_not_fail(session):
    """The NO ACTION foreign key made this raise ForeignKeyViolationError, so the
    instance could not be deleted at all."""
    from sqlalchemy import text

    from brein.store import instances as store_instances

    instance_id = await store_instances.create_instance("sabnzbd", label="cascade-sab")
    await session.execute(
        text(
            "INSERT INTO sabnzbd_server_stats_snapshots (instance_id, payload)"
            " VALUES (:i, '{}'::jsonb)"
        ),
        {"i": instance_id},
    )
    await session.commit()

    assert await store_instances.delete_instance(instance_id) is True


@requires_db
async def test_init_db_is_idempotent(session):
    """init_db() runs on every boot; a second pass must do no DDL and not raise.

    Asserted on the catalog, not just on "it did not raise". The steady-state
    check compared asyncpg's bytes to a str and so never matched, which meant
    every boot dropped all 29 instance foreign keys, swept each table for
    orphans, re-added the constraint and validated it — and this test, which
    only called init_db() twice, stayed green throughout. A constraint that
    survived keeps its oid; one that was rebuilt gets a new one.
    """
    from brein.db import init_db

    async def fk_oids() -> dict[str, int]:
        rows = await session.execute(
            text(
                "SELECT conname, oid FROM pg_constraint"
                " WHERE contype = 'f' AND confrelid = 'app_instances'::regclass"
            )
        )
        await session.commit()
        return {row[0]: int(row[1]) for row in rows.fetchall()}

    await init_db()
    before = await fk_oids()
    assert before, "no instance foreign keys to compare"

    await init_db()
    after = await fk_oids()

    assert after == before, (
        "init_db rebuilt foreign keys it should have left alone: "
        f"{sorted(name for name, oid in after.items() if before.get(name) != oid)}"
    )
