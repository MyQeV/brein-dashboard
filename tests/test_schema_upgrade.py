"""Starting against a database older than the models.

The schema comes from `SQLModel.metadata.create_all` plus idempotent repairs,
with no migration tool. `create_all` creates missing *tables* and never alters
an existing one, so every column added to a model after a deployment first ran
is a column that deployment does not have — and the ad-hoc ALTERs that used to
cover this were deleted once the models moved on. The failure is not subtle:
`store/users.py` selects `role`, so a database without it turns every login
into a 500, and nothing says why at startup.
"""

import time

import pytest
from sqlalchemy import text

from brein.db import (
    _add_missing_columns,
    _column_default_sql,
    _ensure_citext_username,
    _get_engine,
)
from brein.models import tables as _tables  # noqa: F401 — registers metadata
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio(loop_scope="session"), requires_db]


class TestColumnDefaults:
    """The literal used for ADD COLUMN, taken from the model's own default."""

    def test_quotes_strings_and_escapes_them(self):
        column = _tables.User.__table__.c.role
        assert _column_default_sql(column) == "'user'"

    def test_reads_booleans_and_numbers(self):
        assert _column_default_sql(_tables.AppInstance.__table__.c.active) == "TRUE"
        assert _column_default_sql(_tables.AppInstance.__table__.c.sort_order) == "0"

    def test_no_default_means_no_literal(self):
        # username has none, so a NOT NULL add cannot invent one.
        assert _column_default_sql(_tables.User.__table__.c.username) is None

    def test_reads_a_server_default(self):
        """The easy case, which was refused: the database has the literal."""
        column = _tables.ScheduledTaskRun.__table__.c.started_at
        assert not column.nullable
        assert _column_default_sql(column) is not None

    def test_reads_a_default_declared_through_sa_column(self):
        """A Field default never reaches an explicit sa_column.

        These read as NOT NULL with no default at all, so the repair refused
        them — meaning the column could never be added to an existing table,
        which is the only situation the repair exists for.
        """
        for column in (
            _tables.PlexPlaybackSession.__table__.c.watched_seconds,
            _tables.PlexPlaybackSessionActive.__table__.c.view_offset_ms,
            _tables.SabnzbdServerStatsSnapshot.__table__.c.payload,
        ):
            assert not column.nullable
            assert _column_default_sql(column) is not None, column.name


class TestDeclaredDefaultsAreUsable:
    """A NOT NULL column that declares a default must be addable.

    The repair reports and skips a NOT NULL column it cannot derive a value
    for, and the query that selects it then fails on every existing install
    while fresh ones are fine — an upgrade that breaks only in the field.
    Refusing a column with no default at all is correct: `users.username` and
    the foreign keys are required data, and no value can be invented for rows
    that already exist. Refusing one the model *does* default is the bug.
    """

    def test_no_defaulted_column_would_be_refused(self):
        refused = []
        for table in _tables.SQLModel.metadata.sorted_tables:
            for column in table.columns:
                if column.nullable or column.primary_key:
                    continue
                declares_default = (
                    column.default is not None or column.server_default is not None
                )
                if declares_default and _column_default_sql(column) is None:
                    refused.append(f"{table.name}.{column.name}")
        assert refused == [], (
            "these defaulted columns could not be added to an older database: "
            + ", ".join(refused)
        )


class TestUpgradeFromOlderSchema:
    async def test_restores_a_column_the_models_gained(self, session):
        """A column added to the model after deployment is added on next boot."""
        engine = _get_engine()
        await session.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS role"))
        await session.commit()

        await _add_missing_columns(engine)

        present = (
            await session.execute(
                text(
                    "SELECT column_default, is_nullable FROM information_schema.columns"
                    " WHERE table_name = 'users' AND column_name = 'role'"
                )
            )
        ).fetchone()
        assert present is not None, "role was not restored"
        # NOT NULL is only safe with a value for the rows already there.
        assert present[1] == "NO"
        assert "user" in (present[0] or "")

    async def test_makes_usernames_case_insensitive(self, session):
        """An older users table compares case-sensitively until this runs."""
        engine = _get_engine()
        await session.execute(
            text("ALTER TABLE users ALTER COLUMN username TYPE varchar(255)")
        )
        await session.commit()

        await _ensure_citext_username(engine)

        kind = (
            await session.execute(
                text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
                    " WHERE attrelid = 'users'::regclass AND attname = 'username'"
                )
            )
        ).scalar()
        assert kind == "citext"

    async def test_refuses_to_merge_two_accounts_into_one(self, session):
        """ "Admin" and "admin" are two rows until someone decides otherwise.

        Upgrading the column would make them collide with the unique index, so
        the repair reports it and leaves the table alone rather than failing
        the boot or picking a winner.
        """
        engine = _get_engine()
        await session.execute(
            text("ALTER TABLE users ALTER COLUMN username TYPE varchar(255)")
        )
        # Through the model, so its own defaults fill the NOT NULL columns.
        for name in ("Casey", "casey"):
            session.add(
                _tables.User(
                    id=f"upgrade-test-{name}",
                    username=name,
                    hashed_password="x",
                    created_at=time.time(),
                )
            )
        await session.commit()

        try:
            await _ensure_citext_username(engine)

            kind = (
                await session.execute(
                    text(
                        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
                        " WHERE attrelid = 'users'::regclass AND attname = 'username'"
                    )
                )
            ).scalar()
            assert kind != "citext", "the clash should have stopped the upgrade"
        finally:
            await session.execute(
                text("DELETE FROM users WHERE id LIKE 'upgrade-test-%'")
            )
            await session.commit()
            await _ensure_citext_username(engine)
