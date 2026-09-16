"""Shared test configuration.

Environment must be set before *any* ``brein`` module is imported:

* ``brein.config`` reads ``os.environ`` at module import time, so importing it
  first freezes whatever the ambient environment happened to hold.
* ``brein.web.app`` calls ``setup_logging()`` at import time, which does
  ``mkdir`` on ``BREIN_LOG_DIR`` (default ``/app/data/logs``) — unwritable
  outside the container.

Hence the deliberate ordering below and the ``# noqa: E402`` on the deferred
imports.
"""

import os
import tempfile

_LOG_DIR = tempfile.mkdtemp(prefix="brein-test-logs-")

os.environ.setdefault("BREIN_LOG_DIR", _LOG_DIR)
os.environ.setdefault("BREIN_LOG_LEVEL", "WARNING")
os.environ.setdefault("BREIN_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("BREIN_DISABLE_RATE_LIMIT", "1")
os.environ.setdefault(
    "BREIN_BACKUP_DIR", tempfile.mkdtemp(prefix="brein-test-backups-")
)

# Tests that need a database opt in via BREIN_TEST_DATABASE_URL. Without it,
# DATABASE_URL still has to be non-empty or `brein.db` raises at import.
_TEST_DB_URL = os.environ.get("BREIN_TEST_DATABASE_URL", "").strip()
os.environ.setdefault(
    "DATABASE_URL",
    _TEST_DB_URL
    or "postgresql+asyncpg://brein:password@localhost:5432/brein_test",  # pragma: allowlist secret
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

requires_db = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="set BREIN_TEST_DATABASE_URL to run database-backed tests",
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Reset the extension registry cache around every test.

    Without this, whichever test runs first freezes `load_extensions()`'s
    cache for the rest of the session — a problem once Task 2 makes
    `brein.extras.EXTRAS` non-empty and some other test file relies on the
    core-only registry (or vice versa).
    """
    from brein import extensions

    extensions.reset_extensions()
    yield
    extensions.reset_extensions()


@pytest.fixture(scope="session")
def app():
    """The FastAPI app, imported lazily so the env above is applied first."""
    from brein.web.app import app as fastapi_app

    return fastapi_app


def _signed_in_client(app, user, overrides):
    """A `TestClient` whose listed auth dependencies all resolve to `user`.

    The app is deliberately *not* entered as a context manager: its lifespan
    starts the scheduler, opens WebSocket listeners and touches the database,
    none of which these mock-based endpoint tests want.
    """
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    for dependency in overrides:
        app.dependency_overrides[dependency] = lambda: user

    # The setup gate counts users on every request to decide whether the
    # instance is still unclaimed. These tests mock the store and run through
    # a sync TestClient, whose loop is not the one the engine was created on,
    # so that query fails and every response becomes a 503. Claim the instance
    # for the duration instead.
    with patch(
        "brein.web.app.store_users.count_users", new_callable=AsyncMock, return_value=1
    ):
        try:
            yield TestClient(app)
        finally:
            for dependency in overrides:
                app.dependency_overrides.pop(dependency, None)


@pytest.fixture
def client(app):
    """A signed-in `TestClient`, with every auth dependency satisfied."""
    from brein.web import auth as web_auth
    from brein.web.schemas import User

    admin = User(
        id="1",
        username="tester",
        email=None,
        full_name=None,
        disabled=False,
        is_admin=True,
        role="admin",
    )
    overrides = (
        web_auth.get_current_user,
        web_auth.get_current_active_user,
        web_auth.get_current_admin_user,
        web_auth.get_current_user_cookie_or_bearer,
        web_auth.get_current_admin_user_cookie_or_bearer,
    )
    yield from _signed_in_client(app, admin, overrides)


@pytest.fixture
def viewer_client(app):
    """A signed-in `TestClient` for a non-admin user.

    Only the user dependencies are overridden; the admin ones run for real
    on top of them and refuse, so this is the client that can prove a route
    is admin-only.
    """
    from brein.web import auth as web_auth
    from brein.web.schemas import User

    viewer = User(
        id="2",
        username="viewer",
        email=None,
        full_name=None,
        disabled=False,
        is_admin=False,
        role="viewer",
    )
    overrides = (
        web_auth.get_current_user,
        web_auth.get_current_active_user,
        web_auth.get_current_user_cookie_or_bearer,
    )
    yield from _signed_in_client(app, viewer, overrides)


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _db_ready():
    """Prepare the test database once per session.

    ``loop_scope="session"`` matters: async fixtures and the test client must
    share one event loop, or asyncpg connections created here are unusable from
    the tests that borrow them.
    """
    if not _TEST_DB_URL:
        yield
        return

    from brein import db as brein_db

    # Dispose first — an engine bound to a previous loop poisons the pool.
    await brein_db.close_engine()
    await brein_db.init_db()
    yield
    await brein_db.close_engine()


@pytest_asyncio.fixture(loop_scope="session")
async def session(_db_ready):
    """An ``AsyncSession`` bound to the test database."""
    from brein.db import get_session_factory

    async with get_session_factory()() as s:
        yield s
