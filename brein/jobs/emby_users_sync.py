"""Background sync of Emby Users/Query into emby_users table."""

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from brein.integrations.api import emby as emby_api
from brein.jobs._helpers import instance_id_int
from brein.store import emby_users as store_emby_users
from brein.store import instances as store_instances

log = logging.getLogger(__name__)


async def _sync_one_instance(instance_id: int, instance_id_for_config: Any) -> None:
    """Fetch users for one Emby/Jellyfin instance and upsert into emby_users."""
    cfg = await store_instances.get_instance_connection_config(instance_id_for_config)
    if not cfg:
        return
    service_type, base_url, api_key = cfg
    if service_type != "emby" or not base_url or not api_key:
        return

    api = emby_api
    ok, items = await api.get_users(base_url, api_key)
    if not ok:
        # Raised, not returned: the runner records whatever this coroutine
        # does as the task's status, so a refused key showed a green row every
        # minute while the user table went stale. The activity-log jobs
        # already raise for the same reason.
        raise RuntimeError(f"Emby users fetch failed for instance {instance_id}")
    if not items:
        return
    await store_emby_users.replace_users(instance_id, items)
    log.debug(
        "Emby users sync: instance_id=%s synced %d users", instance_id, len(items)
    )


async def run_emby_users_sync_once(instance: dict, _session: AsyncSession) -> None:
    """Scheduled-task entry point: sync one Emby instance's users."""
    iid = instance_id_int(instance)
    if iid is None:
        return
    await _sync_one_instance(iid, instance["id"])


async def run_emby_users_sync_instance(instance_id_for_config: Any) -> None:
    """Sync users for a single Emby instance (e.g. after UserUpdated/UserDeleted WebSocket event)."""
    iid = instance_id_int({"id": instance_id_for_config})
    if iid is None:
        log.debug(
            "Emby users sync: skip instance with non-integer id %s",
            instance_id_for_config,
        )
        return
    try:
        await _sync_one_instance(iid, instance_id_for_config)
    except Exception as e:
        log.warning(
            "Emby users sync failed for instance %s: %s", instance_id_for_config, e
        )


async def run_emby_users_sync() -> None:
    """Run one sync pass: list Emby instances, fetch users, upsert into emby_users."""
    instances = await store_instances.list_instances()
    active = [
        inst
        for inst in instances
        if inst.get("is_configured")
        and inst.get("active", True)
        and (inst.get("service_type") or "") == "emby"
        and instance_id_int(inst) is not None
    ]

    async def _safe_sync(inst: dict) -> None:
        iid = instance_id_int(inst)
        if iid is None:
            return
        try:
            await _sync_one_instance(iid, inst["id"])
        except Exception as e:
            log.warning("Emby users sync failed for instance %s: %s", inst.get("id"), e)

    await asyncio.gather(*[_safe_sync(inst) for inst in active])
