"""Catalog of scheduled task types known to the scheduler.

Each TaskType describes one kind of work the scheduler can run. For instance-bound
task types, the scheduler invokes ``execute`` once per matching ``AppInstance``
(matched by ``service_type``); for global types (``service_type is None``) it
invokes ``execute`` once with ``instance=None``.

The ``execute`` callable receives the loaded task row, the matching instance row
(or None), and an open AsyncSession used for short-lived bookkeeping. Long
work should open its own scoped sessions.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from brein import config as brein_config
from brein.extensions import load_extensions

ExecuteFn = Callable[
    [dict[str, Any], dict[str, Any] | None, AsyncSession], Awaitable[None]
]


@dataclass(frozen=True)
class TaskType:
    key: str
    name: str
    description: str
    category: str  # sync | cache | cleanup | realtime | broadcast
    service_type: str | None  # None=global; else "emby"|"jellyfin"|"plex"|"sabnzbd"
    default_interval_seconds: int
    execute: ExecuteFn


# Lazy adapters that import worker functions on first call to avoid
# import-time cycles between jobs/* modules.


async def _exec_token_cleanup(
    _t: dict[str, Any], _i: dict[str, Any] | None, session: AsyncSession
) -> None:
    from brein.jobs.token_cleanup import run_once

    await run_once(session)


async def _exec_now_playing_broadcast(
    _t: dict[str, Any], _i: dict[str, Any] | None, session: AsyncSession
) -> None:
    from brein.jobs.now_playing_broadcast import run_once

    await run_once(session)


def _instance_exec(module_name: str, fn_name: str) -> ExecuteFn:
    """Build an executor that lazily imports ``module.fn(instance, session)``."""

    async def _exec(
        _t: dict[str, Any], instance: dict[str, Any] | None, session: AsyncSession
    ) -> None:
        if instance is None:
            return
        import importlib

        mod = importlib.import_module(module_name)
        fn = getattr(mod, fn_name)
        await fn(instance, session)

    return _exec


_CORE_TASK_TYPES: dict[str, TaskType] = {
    # Global tasks ----------------------------------------------------------
    "token_cleanup": TaskType(
        key="token_cleanup",
        name="Token cleanup",
        description="Purges expired blacklist + refresh tokens.",
        category="cleanup",
        service_type=None,
        default_interval_seconds=3600,
        execute=_exec_token_cleanup,
    ),
    "now_playing_broadcast": TaskType(
        key="now_playing_broadcast",
        name="Now-playing broadcast",
        description="Broadcasts current now-playing state to WebSocket clients.",
        category="broadcast",
        service_type=None,
        default_interval_seconds=10,
        execute=_exec_now_playing_broadcast,
    ),
    # Per-instance Emby tasks ----------------------------------------------
    "emby_activity_log_sync": TaskType(
        key="emby_activity_log_sync",
        name="Emby activity log sync",
        description="Pulls activity log entries from an Emby instance.",
        category="sync",
        service_type="emby",
        default_interval_seconds=brein_config.EMBY_ACTIVITY_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.emby_activity_log_sync", "run_emby_activity_log_sync_once"
        ),
    ),
    "emby_users_sync": TaskType(
        key="emby_users_sync",
        name="Emby users sync",
        description="Syncs users from an Emby instance.",
        category="sync",
        service_type="emby",
        default_interval_seconds=brein_config.USERS_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.emby_users_sync", "run_emby_users_sync_once"
        ),
    ),
    "emby_items_sync": TaskType(
        key="emby_items_sync",
        name="Emby items sync",
        description="Caches item metadata from an Emby instance.",
        category="sync",
        service_type="emby",
        default_interval_seconds=brein_config.ITEMS_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.emby_items_sync", "run_emby_items_sync_once"
        ),
    ),
    # Per-instance Jellyfin tasks ------------------------------------------
    "jellyfin_activity_log_sync": TaskType(
        key="jellyfin_activity_log_sync",
        name="Jellyfin activity log sync",
        description="Pulls activity log entries from a Jellyfin instance.",
        category="sync",
        service_type="jellyfin",
        default_interval_seconds=brein_config.EMBY_ACTIVITY_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.jellyfin_activity_log_sync",
            "run_jellyfin_activity_log_sync_once",
        ),
    ),
    "jellyfin_users_sync": TaskType(
        key="jellyfin_users_sync",
        name="Jellyfin users sync",
        description="Syncs users from a Jellyfin instance.",
        category="sync",
        service_type="jellyfin",
        default_interval_seconds=brein_config.USERS_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.jellyfin_users_sync", "run_jellyfin_users_sync_once"
        ),
    ),
    "jellyfin_items_sync": TaskType(
        key="jellyfin_items_sync",
        name="Jellyfin items sync",
        description="Caches item metadata from a Jellyfin instance.",
        category="sync",
        service_type="jellyfin",
        default_interval_seconds=brein_config.ITEMS_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.jellyfin_items_sync", "run_jellyfin_items_sync_once"
        ),
    ),
    # Per-instance Plex tasks ----------------------------------------------
    "plex_users_sync": TaskType(
        key="plex_users_sync",
        name="Plex users sync",
        description="Syncs users from a Plex instance.",
        category="sync",
        service_type="plex",
        default_interval_seconds=brein_config.PLEX_USERS_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.plex_users_sync", "run_plex_users_sync_once"
        ),
    ),
    "plex_items_sync": TaskType(
        key="plex_items_sync",
        name="Plex items sync",
        description="Caches item metadata from a Plex instance.",
        category="sync",
        service_type="plex",
        default_interval_seconds=brein_config.ITEMS_SYNC_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.plex_items_sync", "run_plex_items_sync_once"
        ),
    ),
    # Per-instance SABnzbd tasks -------------------------------------------
    "sabnzbd_server_stats_sync": TaskType(
        key="sabnzbd_server_stats_sync",
        name="SABnzbd server stats sync",
        description="Pulls server stats snapshots from a SABnzbd instance.",
        category="sync",
        service_type="sabnzbd",
        default_interval_seconds=brein_config.SABNZBD_SERVER_STATS_INTERVAL_SECONDS,
        execute=_instance_exec(
            "brein.jobs.sabnzbd_server_stats_sync",
            "run_sabnzbd_server_stats_sync_once",
        ),
    ),
}


def task_types() -> dict[str, TaskType]:
    """Core task types plus whatever the loaded extras registered."""
    return {**_CORE_TASK_TYPES, **load_extensions().task_types}


def get_task_type(key: str) -> TaskType | None:
    return task_types().get(key)


def known_keys() -> list[str]:
    return list(task_types().keys())
