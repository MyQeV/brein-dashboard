"""Rebuild the dashboard stats cache. Invoked by the scheduler."""

from sqlalchemy.ext.asyncio import AsyncSession

from brein import cache as brein_cache
from brein.web.routers.dashboard import build_dashboard_stats


async def run_once(_session: AsyncSession) -> None:
    data = await build_dashboard_stats()
    if data is not None:
        await brein_cache.set_cached("dashboard:stats", data)
