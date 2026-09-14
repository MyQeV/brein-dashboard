"""Refresh now-playing state, update cache, broadcast to WebSocket clients."""

from sqlalchemy.ext.asyncio import AsyncSession

from brein import cache as brein_cache
from brein.web.routers.now_playing import (
    NOW_PLAYING_CACHE_KEY,
    broadcast_now_playing,
    refresh_now_playing_state,
)


async def run_once(_session: AsyncSession) -> None:
    data = await refresh_now_playing_state()
    await brein_cache.set_cached(NOW_PLAYING_CACHE_KEY, data)
    await broadcast_now_playing(data)
