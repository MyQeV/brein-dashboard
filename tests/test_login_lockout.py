"""Per-account lockout: counted by username, so it holds behind a proxy
where every login shares one address and the IP limit is shared."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from brein.store import users as store_users
from brein.web import auth as web_auth
from tests.conftest import requires_db

NOW = 1_800_000_000.0
WINDOW = store_users.LOGIN_FAILURE_WINDOW_SECONDS
ATTEMPTS = store_users.LOGIN_LOCKOUT_ATTEMPTS
HASH = web_auth.get_password_hash("right")


def _row(attempts: int, last_failed: float | None) -> dict:
    return {
        "id": "u1",
        "username": "ada",
        "hashed_password": HASH,
        "disabled": False,
        "is_admin": False,
        "role": "user",
        "failed_login_attempts": attempts,
        "last_failed_login_at": last_failed,
    }


# ── login_locked ─────────────────────────────────────────────────────────────


def test_not_locked_below_the_threshold():
    assert not store_users.login_locked(_row(ATTEMPTS - 1, NOW - 1), now=NOW)


def test_locked_at_the_threshold_inside_the_window():
    assert store_users.login_locked(_row(ATTEMPTS, NOW - 1), now=NOW)
    assert store_users.login_locked(_row(ATTEMPTS + 5, NOW - WINDOW + 1), now=NOW)


def test_the_lock_lifts_once_the_window_has_passed():
    assert not store_users.login_locked(_row(ATTEMPTS, NOW - WINDOW), now=NOW)


def test_a_count_without_a_timestamp_never_locks():
    assert not store_users.login_locked(_row(ATTEMPTS, None), now=NOW)


# ── authenticate_user under lockout ──────────────────────────────────────────


async def _authenticate(row, password="right"):  # pragma: allowlist secret
    with patch(
        "brein.store.users.get_user_by_username",
        new_callable=AsyncMock,
        return_value=row,
    ):
        return await web_auth.authenticate_user("ada", password)


async def test_a_locked_account_is_refused_like_an_unknown_user():
    """(None, None), not (None, user_id): attempts during the lockout must
    not extend it, and a locked account is not announced."""
    assert await _authenticate(_row(ATTEMPTS, time.time())) == (None, None)


async def test_a_wrong_password_below_the_threshold_names_the_user():
    user, failed_id = await _authenticate(_row(ATTEMPTS - 1, time.time()), "wrong")
    assert user is None
    assert failed_id == "u1"


async def test_the_right_password_after_the_window_signs_in():
    user, failed_id = await _authenticate(_row(ATTEMPTS, time.time() - WINDOW - 1))
    assert user is not None
    assert user.username == "ada"
    assert failed_id is None


# ── record_login_failure's window ────────────────────────────────────────────


@requires_db
@pytest.mark.asyncio(loop_scope="session")
async def test_failures_only_add_up_inside_the_window(session):
    """The count restarts at one when the previous failure is stale, so only
    failures that follow each other closely reach the lockout."""
    await session.execute(text("DELETE FROM users WHERE username = 'lockout-probe'"))
    await session.commit()
    user_id = await store_users.create_user("lockout-probe", "x")
    try:

        async def _set(attempts: int, last_failed: float) -> None:
            await session.execute(
                text(
                    "UPDATE users SET failed_login_attempts = :n,"
                    " last_failed_login_at = :t WHERE id = :id"
                ),
                {"n": attempts, "t": last_failed, "id": user_id},
            )
            await session.commit()

        await _set(ATTEMPTS - 1, time.time() - WINDOW - 60)
        await store_users.record_login_failure(user_id)
        row = await store_users.get_user_by_username("lockout-probe")
        assert row is not None
        assert row["failed_login_attempts"] == 1
        assert not store_users.login_locked(row)

        await _set(ATTEMPTS - 1, time.time() - 5)
        await store_users.record_login_failure(user_id)
        row = await store_users.get_user_by_username("lockout-probe")
        assert row is not None
        assert row["failed_login_attempts"] == ATTEMPTS
        assert store_users.login_locked(row)

        await store_users.record_login_success(user_id)
        row = await store_users.get_user_by_username("lockout-probe")
        assert row is not None
        assert row["failed_login_attempts"] == 0
        assert not store_users.login_locked(row)
    finally:
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await session.commit()
