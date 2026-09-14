"""Refresh tokens: create, lookup by token, revoke. Stores hashed token in DB."""

import hashlib
import secrets
import time

from sqlalchemy import text

from brein.db import get_session_factory


def _hash_token(plaintext: str) -> str:
    """Return SHA-256 hex digest of the token. Never store plaintext."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def create(
    user_id: str,
    expires_at: float,
) -> tuple[str, str]:
    """Create a refresh token for the user. Returns (plaintext_token, token_id).
    Caller must send plaintext_token to client once; store only the id for revocation."""
    token_id = secrets.token_urlsafe(16)
    plaintext = secrets.token_urlsafe(32)
    token_hash = _hash_token(plaintext)
    created_at = time.time()
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)"
                " VALUES (:id, :user_id, :token_hash, :expires_at, :created_at)"
            ),
            {
                "id": token_id,
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at,
                "created_at": created_at,
            },
        )
        await session.commit()
    return plaintext, token_id


async def get_user_id_by_token(plaintext: str) -> str | None:
    """Return user_id if the token is valid and not expired, else None."""
    token_hash = _hash_token(plaintext)
    now = time.time()
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT user_id FROM refresh_tokens"
                " WHERE token_hash = :token_hash AND expires_at > :now"
            ),
            {"token_hash": token_hash, "now": now},
        )
        row = result.fetchone()
        return row[0] if row else None


async def get_token_info(plaintext: str) -> dict[str, str | float] | None:
    """Return {user_id, expires_at} if token is valid and not expired, else None."""
    token_hash = _hash_token(plaintext)
    now = time.time()
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT user_id, expires_at FROM refresh_tokens"
                " WHERE token_hash = :token_hash AND expires_at > :now"
            ),
            {"token_hash": token_hash, "now": now},
        )
        row = result.fetchone()
        return {"user_id": row[0], "expires_at": float(row[1])} if row else None


async def revoke(token_id: str) -> None:
    """Revoke a refresh token by id (e.g. on logout)."""
    async with get_session_factory()() as session:
        await session.execute(
            text("DELETE FROM refresh_tokens WHERE id = :id"),
            {"id": token_id},
        )
        await session.commit()


async def revoke_by_token(plaintext: str) -> bool:
    """Revoke a refresh token by plaintext. Returns True if a row was deleted."""
    token_hash = _hash_token(plaintext)
    async with get_session_factory()() as session:
        result = await session.execute(
            text("DELETE FROM refresh_tokens WHERE token_hash = :token_hash"),
            {"token_hash": token_hash},
        )
        await session.commit()
        return result.rowcount > 0


async def revoke_all_for_user(user_id: str) -> int:
    """Revoke all refresh tokens for a user. Returns number of rows deleted."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text("DELETE FROM refresh_tokens WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        await session.commit()
        return result.rowcount


async def cleanup_expired() -> int:
    """Remove expired refresh tokens. Returns number of rows deleted."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text("DELETE FROM refresh_tokens WHERE expires_at <= :now"),
            {"now": time.time()},
        )
        await session.commit()
        return result.rowcount
