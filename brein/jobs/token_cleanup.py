"""Purge expired refresh tokens, blacklist entries, and in-process cache. Hourly."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from brein import cache as brein_cache
from brein.store import blacklist as store_blacklist
from brein.store import refresh_tokens as store_refresh_tokens

log = logging.getLogger(__name__)


async def run_once(_session: AsyncSession) -> None:
    rn = await store_refresh_tokens.cleanup_expired()
    bn = await store_blacklist.cleanup_expired()
    cn = brein_cache.sweep_expired()
    if rn > 0 or bn > 0 or cn > 0:
        log.info(
            "Cleanup: removed %d expired refresh tokens, %d blacklist entries, %d cache entries",
            rn,
            bn,
            cn,
        )
