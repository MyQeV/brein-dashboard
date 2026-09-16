"""User persistence for auth: get by username, create, count."""

import time
import uuid
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory

# Valid role values.
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_VIEWER, ROLE_USER}

# Per-account brute-force lockout: this many failures, each within the window
# of the one before, lock the account until the window has passed since the
# last one. Counted by username, so it holds even when every login arrives
# from one address (the bundled frontend's proxy) and the IP limit is shared.
LOGIN_LOCKOUT_ATTEMPTS = 10
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60


def login_locked(row: dict[str, Any], now: float | None = None) -> bool:
    """Whether a user row is inside its lockout window."""
    attempts = int(row.get("failed_login_attempts") or 0)
    last_failed = row.get("last_failed_login_at")
    if attempts < LOGIN_LOCKOUT_ATTEMPTS or last_failed is None:
        return False
    return (now if now is not None else time.time()) - float(
        last_failed
    ) < LOGIN_FAILURE_WINDOW_SECONDS


def _resolve_role(role: str | None, is_admin: bool | None) -> str:
    """Normalise role string; fall back to is_admin flag when role not supplied."""
    if role and role in VALID_ROLES:
        return role
    if is_admin:
        return ROLE_ADMIN
    return ROLE_USER


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Return user row as dict or None."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT id, username, hashed_password, email, full_name, is_admin, disabled, created_at, role,"
                " emby_instance_id, emby_username, jellyfin_instance_id, jellyfin_username,"
                " failed_login_attempts, last_failed_login_at"
                " FROM users WHERE username = :username"
            ),
            {"username": username.strip()},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None


async def create_user(
    username: str,
    hashed_password: str,
    email: str | None = None,
    full_name: str | None = None,
    is_admin: bool = False,
    role: str | None = None,
    emby_instance_id: int | None = None,
    emby_username: str | None = None,
    jellyfin_instance_id: int | None = None,
    jellyfin_username: str | None = None,
) -> str:
    """Create a user; returns user id. Raises ValueError if username already exists."""
    from sqlalchemy.exc import IntegrityError

    username = username.strip()
    if not username:
        raise ValueError("username is required")
    resolved_role = _resolve_role(role, is_admin)
    admin_flag = resolved_role == ROLE_ADMIN
    user_id = str(uuid.uuid4())
    created_at = time.time()
    try:
        async with get_session_factory()() as session:
            await session.execute(
                text(
                    "INSERT INTO users"
                    " (id, username, hashed_password, email, full_name, is_admin, disabled, created_at, role,"
                    " emby_instance_id, emby_username, jellyfin_instance_id, jellyfin_username, failed_login_attempts)"
                    " VALUES (:id, :username, :hashed_password, :email, :full_name, :is_admin, :disabled, :created_at, :role,"
                    " :emby_instance_id, :emby_username, :jellyfin_instance_id, :jellyfin_username, 0)"
                ),
                {
                    "id": user_id,
                    "username": username,
                    "hashed_password": hashed_password,
                    "email": (email or "").strip() or None,
                    "full_name": (full_name or "").strip() or None,
                    "is_admin": admin_flag,
                    "disabled": False,
                    "created_at": created_at,
                    "role": resolved_role,
                    "emby_instance_id": emby_instance_id,
                    "emby_username": emby_username,
                    "jellyfin_instance_id": jellyfin_instance_id,
                    "jellyfin_username": jellyfin_username,
                },
            )
            await session.commit()
    except IntegrityError:
        raise ValueError(f"Username already exists: {username}")
    return user_id


async def count_users() -> int:
    """Return total number of users (for first-time setup check)."""
    async with get_session_factory()() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        val = result.scalar()
        return int(val) if val is not None else 0


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    """Return user row as dict or None."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT id, username, hashed_password, email, full_name, is_admin, disabled, created_at, role"
                " FROM users WHERE id = :user_id"
            ),
            {"user_id": user_id},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None


async def update_user(
    user_id: str,
    *,
    email: str | None = None,
    full_name: str | None = None,
    hashed_password: str | None = None,
) -> None:
    """Update user by id. Only provided fields are updated. Raises ValueError if user not found."""
    row = await get_user_by_id(user_id)
    if not row:
        raise ValueError("User not found")
    updates = []
    params: dict[str, Any] = {"user_id": user_id}
    if email is not None:
        updates.append("email = :email")
        params["email"] = (email or "").strip() or None
    if full_name is not None:
        updates.append("full_name = :full_name")
        params["full_name"] = (full_name or "").strip() or None
    if hashed_password is not None:
        updates.append("hashed_password = :hashed_password")
        params["hashed_password"] = hashed_password
    if not updates:
        return
    async with get_session_factory()() as session:
        await session.execute(
            text("UPDATE users SET " + ", ".join(updates) + " WHERE id = :user_id"),
            params,
        )
        await session.commit()


async def update_user_role_status(
    user_id: str,
    *,
    role: str,
    disabled: bool,
) -> None:
    """Update role and disabled for a user. Raises ValueError if user not found or invalid role."""
    if role not in VALID_ROLES:
        raise ValueError(
            f"Invalid role: {role!r}. Must be one of {sorted(VALID_ROLES)}"
        )
    row = await get_user_by_id(user_id)
    if not row:
        raise ValueError("User not found")
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE users SET role = :role, is_admin = :is_admin, disabled = :disabled"
                " WHERE id = :user_id"
            ),
            {
                "user_id": user_id,
                "role": role,
                "is_admin": role == ROLE_ADMIN,
                "disabled": disabled,
            },
        )
        await session.commit()


async def list_users() -> list[dict[str, Any]]:
    """Return all users as dicts (no hashed_password). Ordered by username."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT id, username, email, full_name, is_admin, disabled, created_at, role,"
                " last_login_at, last_failed_login_at, failed_login_attempts, last_login_ip"
                " FROM users ORDER BY username"
            )
        )
        return [dict(r) for r in result.mappings().fetchall()]


async def get_usernames_set() -> set[str]:
    """Return a set of all existing usernames (for import deduplication)."""
    async with get_session_factory()() as session:
        result = await session.execute(text("SELECT username FROM users"))
        return {r[0] for r in result.fetchall()}


async def record_login_success(
    user_id: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Record a successful login: update last_login_at, reset failed_login_attempts."""
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE users SET last_login_at = :ts, failed_login_attempts = 0,"
                " last_login_ip = :ip, last_login_user_agent = :ua WHERE id = :id"
            ),
            {"ts": time.time(), "ip": ip, "ua": user_agent, "id": user_id},
        )
        await session.commit()


async def record_login_failure(user_id: str) -> None:
    """Record a failed login attempt: increment failed_login_attempts and update last_failed_login_at.

    The count restarts at one when the previous failure is older than the
    window, so only failures that follow each other closely add up to a lockout.
    """
    now = time.time()
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE users SET failed_login_attempts = CASE"
                " WHEN last_failed_login_at IS NULL OR last_failed_login_at < :window_start"
                " THEN 1 ELSE failed_login_attempts + 1 END,"
                " last_failed_login_at = :ts WHERE id = :id"
            ),
            {
                "ts": now,
                "window_start": now - LOGIN_FAILURE_WINDOW_SECONDS,
                "id": user_id,
            },
        )
        await session.commit()
