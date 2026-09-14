"""Registry of background tasks to run after a user logs in. Extensible for future tasks (e.g. dashboard stats prewarm)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

# Async callables that take no arguments. Add more for other post-login prewarm logic.
ON_LOGIN_REFRESH_TASKS: list[Callable[[], Awaitable[None]]] = []
_background_tasks: set[asyncio.Task] = set()


async def _run_one(coro: Awaitable[None]) -> None:
    """Run a single task; log and swallow errors so one failure does not affect others."""
    try:
        await coro
    except Exception as e:
        log.warning("On-login task error: %s", e, exc_info=True)


def run_on_login_tasks() -> None:
    """Schedule all registered on-login tasks (fire-and-forget). Do not await."""
    for task_fn in ON_LOGIN_REFRESH_TASKS:
        task = asyncio.create_task(_run_one(task_fn()))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
