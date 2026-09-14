"""Token blacklist: PostgreSQL-backed.

On logout the JTI is stored with its expiry time. Expired entries are cleaned
up by the background cleanup task alongside refresh tokens.
"""

import logging
import time

from sqlalchemy import text

from brein.db import get_session_factory

log = logging.getLogger(__name__)


async def add_to_blacklist(jti: str, exp: float) -> None:
    """Record a token id as blacklisted until its expiry. Idempotent for same jti."""
    try:
        async with get_session_factory()() as session:
            await session.execute(
                text(
                    "INSERT INTO token_blacklist (jti, expires_at) VALUES (:jti, :expires_at)"
                    " ON CONFLICT (jti) DO NOTHING"
                ),
                {"jti": jti, "expires_at": exp},
            )
            await session.commit()
    except Exception as exc:
        log.warning("add_to_blacklist error: %s", exc)


async def is_blacklisted(jti: str) -> bool:
    """Return True if jti is in the blacklist and not yet expired."""
    try:
        now = time.time()
        async with get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT 1 FROM token_blacklist WHERE jti = :jti AND expires_at > :now"
                ),
                {"jti": jti, "now": now},
            )
            return result.fetchone() is not None
    except Exception as exc:
        log.error(
            "is_blacklisted DB error — treating token as revoked (fail-closed): %s", exc
        )
        return True


async def cleanup_expired() -> int:
    """Remove expired blacklist entries. Returns number of rows deleted."""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                text("DELETE FROM token_blacklist WHERE expires_at <= :now"),
                {"now": time.time()},
            )
            await session.commit()
            return result.rowcount
    except Exception as exc:
        log.warning("cleanup_expired error: %s", exc)
        return 0
