"""Fire-and-forget task helper.

``asyncio.create_task`` only holds a weak reference to the task it returns, so
a task nobody keeps a reference to can be garbage collected while it is still
running — it simply stops, with no traceback. Every fire-and-forget call site
must therefore keep the task alive until it finishes, and log whatever it
raised, which is what this does.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
    """Schedule ``coro`` and keep a strong reference until it completes."""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    task.add_done_callback(lambda t: _log_result(t, name))
    return task


def _log_result(task: asyncio.Task, name: str) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("Background task %s failed: %s", name, exc, exc_info=exc)


def pending_count() -> int:
    """Number of tracked tasks still running (used by tests)."""
    return len(_tasks)
