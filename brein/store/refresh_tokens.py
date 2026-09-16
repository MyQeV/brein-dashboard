"""Refresh tokens: create, lookup by token, revoke. Stores hashed token in DB."""

import hashlib
import secrets
import time

from sqlalchemy import text

from brein import cache as brein_cache
from brein.db import get_session_factory

# How long a rotated-away token still resolves to its replacement. Two tabs
# refreshing at once both present the same token; without this the loser gets
# a 401 and signs the user out of a session that is perfectly valid.
ROTATION_GRACE_SECONDS = 30


def _hash_token(plaintext: str) -> str:
    """Return SHA-256 hex digest of the token. Never store plaintext."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _rotation_key(plaintext: str) -> str:
    return f"refresh_rotated:{_hash_token(plaintext)}"


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


async def rotate(plaintext: str, user_id: str, expires_at: float) -> tuple[str, str]:
    """Replace a refresh token. Returns (new_plaintext, new_token_id).

    The new token is created before the old one is revoked, so a failed
    insert leaves the old token valid rather than the session lost. The
    replacement's plaintext is then held in the process cache, keyed by the
    old token's hash, for ROTATION_GRACE_SECONDS — long enough for a
    concurrent presentation of the old token to be answered with it.
    """
    new_plaintext, token_id = await create(user_id, expires_at)
    await revoke_by_token(plaintext)
    await brein_cache.set_cached(
        _rotation_key(plaintext), new_plaintext, ttl_seconds=ROTATION_GRACE_SECONDS
    )
    return new_plaintext, token_id


async def get_rotation_replacement(plaintext: str) -> str | None:
    """Return the token a just-rotated token was replaced with, if still within grace."""
    replacement = await brein_cache.get_cached(_rotation_key(plaintext))
    return replacement if isinstance(replacement, str) else None


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
