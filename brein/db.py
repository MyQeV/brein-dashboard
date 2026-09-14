"""Async PostgreSQL engine and session factory (SQLModel / SQLAlchemy)."""

import logging
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from brein.config import (
    DB_POOL_SIZE,
    DB_MAX_OVERFLOW,
)

log = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine():
    """Return (or lazily create) the async engine using the current DATABASE_URL."""
    global _engine, _session_factory
    if _engine is None:
        from brein import config as brein_config

        url = brein_config.DATABASE_URL
        if not url:
            log.error(
                "DATABASE_URL is not set. Example: postgresql+asyncpg://brein:password@localhost:5432/brein"  # pragma: allowlist secret
            )
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Example: postgresql+asyncpg://brein:password@localhost:5432/brein"  # pragma: allowlist secret
            )
        try:
            _engine = create_async_engine(
                url,
                echo=False,
                pool_pre_ping=True,
                pool_size=DB_POOL_SIZE,
                max_overflow=DB_MAX_OVERFLOW,
            )
            _session_factory = async_sessionmaker(
                _engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            log.info(
                "Database engine created with pool_size=%d and max_overflow=%d",
                DB_POOL_SIZE,
                DB_MAX_OVERFLOW,
            )
        except Exception as e:
            log.error("Failed to create database engine: %s", e)
            raise
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory, creating the engine on first call."""
    _get_engine()
    if _session_factory is None:
        raise RuntimeError(
            "Session factory was not initialised — call _get_engine() first"
        )
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield an AsyncSession per request."""
    factory = get_session_factory()
    async with factory() as session:
        log.debug("Session created")
        try:
            yield session
        finally:
            log.debug("Session closed")


# Every table carrying a NOT NULL instance_id must cascade from app_instances.
# Without the FK, deleting an instance orphans these rows forever: no read path
# can reach them (they all filter by instance_id) and they can resurface under a
# recycled serial id.
INSTANCE_SCOPED_TABLES: tuple[str, ...] = (
    "emby_activity_log_entries",
    "emby_items",
    "emby_items_state",
    "emby_metrics_snapshot",
    "emby_metrics_snapshot_item",
    "emby_metrics_snapshot_user",
    "emby_playback_sessions",
    "emby_playback_sessions_state",
    "emby_user_item_id_skip",
    "emby_users",
    "jellyfin_activity_log_entries",
    "jellyfin_items",
    "jellyfin_items_state",
    "jellyfin_metrics_snapshot",
    "jellyfin_metrics_snapshot_item",
    "jellyfin_metrics_snapshot_user",
    "jellyfin_playback_sessions",
    "jellyfin_playback_sessions_state",
    "jellyfin_users",
    "plex_items",
    "plex_items_state",
    "plex_metrics_snapshot",
    "plex_metrics_snapshot_item",
    "plex_metrics_snapshot_user",
    "plex_playback_sessions",
    "plex_playback_sessions_active",
    "plex_users",
    "plex_ws_events",
    # Existing FK is NO ACTION, which does not orphan rows — it makes deleting
    # a SABnzbd instance fail outright. Converted to CASCADE below.
    "sabnzbd_server_stats_snapshots",
)

# Tables whose primary key does not start with instance_id. Without a dedicated
# index every cascaded delete sequentially scans them.
INSTANCE_ID_INDEX_TABLES: tuple[str, ...] = (
    "emby_metrics_snapshot",
    "emby_metrics_snapshot_item",
    "emby_metrics_snapshot_user",
    "jellyfin_metrics_snapshot",
    "jellyfin_metrics_snapshot_item",
    "jellyfin_metrics_snapshot_user",
    "plex_metrics_snapshot",
    "plex_metrics_snapshot_item",
    "plex_metrics_snapshot_user",
)

# (table, column) pairs the metrics and session-rebuild queries filter on by
# instance and time. The timestamps are ISO-8601 text, which sorts
# chronologically, so a btree on them still prunes a date range. The item
# tables are filtered by type instead, for the never-played anti-join.
TIME_RANGE_INDEXES: tuple[tuple[str, str], ...] = (
    ("emby_items", "type"),
    ("jellyfin_items", "type"),
    ("plex_items", "type"),
    ("emby_playback_sessions", "start_time"),
    ("jellyfin_playback_sessions", "start_time"),
    ("plex_playback_sessions", "start_time"),
    ("emby_activity_log_entries", "date"),
    ("jellyfin_activity_log_entries", "date"),
)

_ORPHAN_BATCH = 10_000

_FK_PROBE = """
    SELECT c.conname, c.confdeltype, c.convalidated
    FROM pg_constraint c
    JOIN pg_attribute a
      ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    WHERE c.contype = 'f'
      AND c.conrelid = to_regclass(:table_name)
      AND c.confrelid = to_regclass('public.app_instances')
      AND cardinality(c.conkey) = 1
      AND a.attname = 'instance_id'
"""


async def _sweep_orphans(engine, table: str) -> int:
    """Delete rows whose instance is gone, in batches, before adding the FK.

    Batched by ctid in separate transactions so a multi-million-row table does
    not become one enormous transaction and WAL burst.
    """
    from sqlalchemy import text as _text

    sql = _text(
        f"""
        WITH doomed AS (
            SELECT t.ctid FROM "{table}" t
            LEFT JOIN app_instances a ON a.id = t.instance_id
            WHERE a.id IS NULL
            LIMIT {_ORPHAN_BATCH}
        )
        DELETE FROM "{table}" t USING doomed d WHERE t.ctid = d.ctid
        """
    )
    removed = 0
    while True:
        async with engine.begin() as conn:
            result = await conn.execute(sql)
        count = result.rowcount or 0
        removed += count
        if count < _ORPHAN_BATCH:
            break
    if removed:
        log.warning("Removed %d orphaned rows from %s", removed, table)
    return removed


def _column_default_sql(column) -> str | None:
    """A literal for ADD COLUMN, from whatever default the model declares.

    A NOT NULL column cannot be added to a table with rows unless a value is
    supplied for them, and the models express that as a Python-side default
    (`Field(default="user")`) which never reaches the database.

    A column declared with `server_default` is the easy case — the database
    has the literal already — but returning None for it made the caller treat
    a NOT NULL column as unaddable and refuse it. That covered the file's own
    convention for timestamps (`server_default=func.now()`), so the next such
    column added to an existing table would have been refused on every
    upgrade: fresh installs get it from `create_all`, everyone else 500s on
    the first query that selects it. The same held for a column declared
    through `sa_column=Column(..., nullable=False)`, where SQLModel keeps the
    Column as given and no Python-side default reaches this function; those
    are read from the Column's own `default` below.
    """
    server_default = getattr(column, "server_default", None)
    if server_default is not None:
        arg = getattr(server_default, "arg", None)
        text_clause = getattr(server_default, "text", None)
        if text_clause:
            return str(text_clause)
        if arg is not None:
            return str(arg)
        return None
    default = getattr(column, "default", None)
    value = getattr(default, "arg", None) if default is not None else None
    if value is None or callable(value):
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


async def _add_missing_columns(engine) -> None:
    """Add columns the models declare and an older database does not have.

    `create_all` creates missing *tables*; it never alters an existing one. The
    ad-hoc ALTERs that used to cover this were removed once the models had
    moved on, so a database created before a column was added keeps failing
    every query that selects it — `store/users.py` selects `role`, and an
    upgrade without it turns every login into a 500. Nullable and defaulted
    columns can always be added safely; anything else is reported rather than
    guessed at, since a value would have to be invented for existing rows.
    """
    from sqlalchemy import text as _text

    async with engine.begin() as conn:
        existing = await conn.execute(
            _text(
                "SELECT table_name, column_name FROM information_schema.columns"
                " WHERE table_schema = current_schema()"
            )
        )
        have: dict[str, set[str]] = {}
        for table_name, column_name in existing:
            have.setdefault(table_name, set()).add(column_name)

        for table in SQLModel.metadata.sorted_tables:
            present = have.get(table.name)
            if present is None:
                continue  # create_all just made it, or it is not ours
            for column in table.columns:
                if column.name in present:
                    continue
                ddl = column.type.compile(engine.dialect)
                default_sql = _column_default_sql(column)
                if not column.nullable and default_sql is None:
                    log.error(
                        "Column %s.%s is missing and cannot be added"
                        " automatically: it is NOT NULL with no default, so a"
                        " value would have to be invented for existing rows.",
                        table.name,
                        column.name,
                    )
                    continue
                suffix = f" NOT NULL DEFAULT {default_sql}" if default_sql else ""
                try:
                    await conn.execute(
                        _text(
                            f'ALTER TABLE "{table.name}"'
                            f' ADD COLUMN IF NOT EXISTS "{column.name}" {ddl}{suffix}'
                        )
                    )
                    log.info("Added missing column %s.%s", table.name, column.name)
                except Exception:
                    log.exception(
                        "Could not add missing column %s.%s", table.name, column.name
                    )


async def _ensure_citext_username(engine) -> None:
    """Make `users.username` case-insensitive on databases that predate CITEXT.

    The model has declared CITEXT since 2026-03-28, but `create_all` does not
    change an existing column, and nothing lowercases the value in Python — so
    an older database still compares case-sensitively — so two installs on the
    same code behave differently: one treats "Admin" and "admin" as a single
    account, the other as two.
    """
    from sqlalchemy import text as _text

    async with engine.begin() as conn:
        current = (
            await conn.execute(
                _text(
                    "SELECT format_type(a.atttypid, a.atttypmod)"
                    " FROM pg_attribute a"
                    " WHERE a.attrelid = to_regclass('users')"
                    "   AND a.attname = 'username' AND a.attnum > 0"
                )
            )
        ).scalar()
        if current is None or current == "citext":
            return

        clash = (
            await conn.execute(
                _text(
                    "SELECT lower(username) FROM users"
                    " GROUP BY 1 HAVING count(*) > 1 LIMIT 1"
                )
            )
        ).scalar()
        if clash is not None:
            log.error(
                "users.username cannot be made case-insensitive: %r exists more"
                " than once when compared case-insensitively. Rename one of"
                " those accounts and restart.",
                clash,
            )
            return

        try:
            await conn.execute(
                _text("ALTER TABLE users ALTER COLUMN username TYPE citext")
            )
            log.info("users.username upgraded to citext (case-insensitive logins)")
        except Exception:
            log.exception("Could not upgrade users.username to citext")


async def _ensure_instance_cascades(engine) -> None:
    """Give every instance-scoped table an ON DELETE CASCADE FK to app_instances.

    Idempotent: once applied this does one catalog query per table and no DDL,
    which matters because init_db() runs on every boot. Adding the constraint
    NOT VALID and validating separately keeps the ACCESS EXCLUSIVE lock to the
    catalog update rather than a full table scan — and a NOT VALID FK already
    cascades, so the defect is fixed even if validation is deferred.
    """
    from sqlalchemy import text as _text

    for table in INSTANCE_ID_INDEX_TABLES:
        try:
            async with engine.begin() as conn:
                await conn.execute(_text("SET LOCAL lock_timeout = '5s'"))
                await conn.execute(
                    _text(
                        f'CREATE INDEX IF NOT EXISTS "ix_{table}_instance_id" '
                        f'ON "{table}" (instance_id)'
                    )
                )
        except Exception:
            log.exception("Could not create instance_id index on %s", table)

    # The dashboard reads these tables by instance and time window on every
    # request; with only an instance_id index each of the ~14 metrics queries
    # scanned the whole table.
    for table, column in TIME_RANGE_INDEXES:
        try:
            async with engine.begin() as conn:
                await conn.execute(_text("SET LOCAL lock_timeout = '5s'"))
                await conn.execute(
                    _text(
                        f'CREATE INDEX IF NOT EXISTS "ix_{table}_instance_{column}" '
                        f'ON "{table}" (instance_id, {column})'
                    )
                )
        except Exception:
            log.exception(
                "Could not create (instance_id, %s) index on %s", column, table
            )

    failed: list[str] = []
    for table in INSTANCE_SCOPED_TABLES:
        constraint = f"{table}_instance_id_fkey"
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        _text(_FK_PROBE), {"table_name": f"public.{table}"}
                    )
                ).first()

            # asyncpg decodes Postgres' "char" type as bytes, so comparing to
            # the str "c" was never true: the steady-state check never fired,
            # and every boot dropped all 29 instance foreign keys, swept each
            # table for orphans, re-added the constraint NOT VALID and then
            # validated it — two full scans per table, every start. Worse, the
            # drop and the add are separate transactions under a 5s
            # lock_timeout, so anything holding a lock in between left that
            # table with no foreign key at all until the next restart, which
            # is precisely how deleting an instance silently orphaned rows.
            delete_rule = row.confdeltype if row is not None else None
            if isinstance(delete_rule, (bytes, bytearray)):
                delete_rule = delete_rule.decode()

            if row is not None and delete_rule == "c" and row.convalidated:
                continue  # steady state

            if row is not None and delete_rule != "c":
                async with engine.begin() as conn:
                    await conn.execute(_text("SET LOCAL lock_timeout = '5s'"))
                    await conn.execute(
                        _text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{row.conname}"')
                    )
                row = None

            # Always sweep before adding or validating: a NOT VALID constraint
            # never checked the rows that already existed, so a run interrupted
            # between ADD and VALIDATE can leave orphans that fail validation.
            await _sweep_orphans(engine, table)

            if row is None:
                async with engine.begin() as conn:
                    await conn.execute(_text("SET LOCAL lock_timeout = '5s'"))
                    await conn.execute(
                        _text(
                            f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" '
                            "FOREIGN KEY (instance_id) REFERENCES app_instances (id) "
                            "ON DELETE CASCADE NOT VALID"
                        )
                    )
                name = constraint
            else:
                name = row.conname

            async with engine.begin() as conn:
                await conn.execute(
                    _text(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{name}"')
                )
        except Exception:
            # One table failing to lock is not worth refusing to boot over; the
            # next start retries.
            log.exception("Could not ensure delete cascade on %s", table)
            failed.append(table)

    if failed:
        log.error("Instance-delete cascade is NOT in place for: %s", ", ".join(failed))


async def init_db() -> None:
    """Create all tables if they do not exist (runs on app startup)."""
    from brein.models import tables as _tables  # noqa: F401 — registers SQLModel metadata
    from brein.extensions import load_extensions

    for _ in load_extensions().models:
        pass  # imported for metadata

    engine = _get_engine()
    from sqlalchemy import text as _text

    async with engine.begin() as conn:
        await conn.execute(_text("CREATE EXTENSION IF NOT EXISTS citext"))

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    await _add_missing_columns(engine)
    await _ensure_citext_username(engine)

    async with engine.begin() as conn:
        await conn.execute(
            _text(
                "ALTER TABLE plex_playback_sessions_active "
                "ADD COLUMN IF NOT EXISTS account_title VARCHAR(512)"
            )
        )
        await conn.execute(
            _text(
                "ALTER TABLE plex_playback_sessions "
                "ADD COLUMN IF NOT EXISTS account_title VARCHAR(512)"
            )
        )

        await conn.execute(
            _text(
                """
                DELETE FROM scheduled_tasks t1
                WHERE t1.instance_id IS NULL
                  AND EXISTS (
                    SELECT 1 FROM scheduled_tasks t2
                    WHERE t2.instance_id IS NULL
                      AND t2.key = t1.key
                      AND t2.id < t1.id
                  )
                """
            )
        )
        # Only rebuild the constraint when it is not already what we want:
        # dropping and re-adding it took an ACCESS EXCLUSIVE lock and rebuilt
        # the index on every single boot.
        already = (
            await conn.execute(
                _text(
                    "SELECT i.indnullsnotdistinct FROM pg_index i"
                    " JOIN pg_class c ON c.oid = i.indexrelid"
                    " WHERE c.relname = 'uq_scheduled_tasks_key_instance'"
                )
            )
        ).scalar()
        if already is not True:
            await conn.execute(
                _text(
                    "ALTER TABLE scheduled_tasks "
                    "DROP CONSTRAINT IF EXISTS uq_scheduled_tasks_key_instance"
                )
            )
            await conn.execute(
                _text(
                    "ALTER TABLE scheduled_tasks "
                    "ADD CONSTRAINT uq_scheduled_tasks_key_instance "
                    "UNIQUE NULLS NOT DISTINCT (key, instance_id)"
                )
            )

    await _ensure_instance_cascades(engine)

    log.info("Database schema initialised")


async def close_engine() -> None:
    """Dispose the engine connection pool (runs on app shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("Database engine disposed")


def reset_engine() -> None:
    """Reset the cached engine — used in tests to force recreation with a new DATABASE_URL."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
    log.info("Database engine reset")
