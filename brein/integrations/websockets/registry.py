"""The live WebSocket listeners, keyed by instance.

Listeners used to be started once during startup and never touched again, so
the set of live connections was whatever the instance table happened to say at
boot. Adding a server, or correcting its token, changed nothing until someone
restarted the container — and deactivating or deleting one left its listener
reconnecting against a server it should no longer be talking to.

This keeps one task per instance and lets the instance routes bring it in line
with the row that was just written.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

# instance_id -> the task running that instance's listener.
_listeners: dict[int, asyncio.Task] = {}

# One lock per instance. `restart` pops the old task before awaiting its
# cancellation, so two overlapping writes to the same instance — a
# double-clicked Save — could both find nothing running, both start a
# listener, and leave whichever stored its task first untracked: still
# connected, still writing, and invisible to `stop_all` at shutdown.
_locks: dict[int, asyncio.Lock] = {}


def _lock_for(instance_id: int) -> asyncio.Lock:
    lock = _locks.get(instance_id)
    if lock is None:
        lock = _locks[instance_id] = asyncio.Lock()
    return lock


# How a listener is built for a given instance. Set once by the app on startup,
# so this module needs no import of the integrations or the store.
ListenerFactory = Callable[[int], Awaitable[asyncio.Task | None]]
_factory: ListenerFactory | None = None


def configure(factory: ListenerFactory) -> None:
    """Register how to start a listener for an instance id."""
    global _factory
    _factory = factory


def is_running(instance_id: int) -> bool:
    task = _listeners.get(instance_id)
    return task is not None and not task.done()


def track(instance_id: int, task: asyncio.Task) -> None:
    """Record a listener started elsewhere, so it can be stopped later."""
    _listeners[instance_id] = task


async def stop(instance_id: int) -> None:
    """Cancel an instance's listener, if it has one."""
    task = _listeners.pop(instance_id, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("Listener for instance %s failed while stopping", instance_id)
    log.info("Stopped WebSocket listener for instance_id=%s", instance_id)


async def restart(instance_id: int) -> None:
    """Stop whatever is running for this instance and start it afresh.

    Called after an instance is written: the host or token may have changed,
    and a listener holding the old ones would reconnect with them forever.
    """
    async with _lock_for(instance_id):
        await stop(instance_id)
        if _factory is None:
            return
        try:
            task = await _factory(instance_id)
        except Exception:
            log.exception("Could not start WebSocket listener for %s", instance_id)
            return
        if task is not None:
            _listeners[instance_id] = task
            log.info("Started WebSocket listener for instance_id=%s", instance_id)


async def stop_all() -> None:
    """Cancel every listener — used on shutdown."""
    for instance_id in list(_listeners):
        await stop(instance_id)


def running_ids() -> list[int]:
    return [iid for iid, task in _listeners.items() if not task.done()]


def snapshot() -> dict[int, Any]:
    """Diagnostic view: which instances have a live listener."""
    return {iid: not task.done() for iid, task in _listeners.items()}
