"""Background sync of Plex home users (via plex.tv) into plex_users table."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from brein.integrations.api import plex as plex_api
from brein.jobs._helpers import instance_id_int
from brein.store import instances as store_instances
from brein.store import plex_users as store_plex_users

log = logging.getLogger(__name__)


async def _sync_one_instance(instance_id: int, instance_id_for_config: int) -> None:
    """Fetch plex.tv home users for one Plex instance and replace into plex_users."""
    cfg = await store_instances.get_instance_connection_config(instance_id_for_config)
    if not cfg:
        return
    service_type, base_url, api_key = cfg
    if service_type != "plex" or not api_key:
        return

    users = await plex_api.get_users(base_url, api_key)
    if not users:
        log.warning(
            "Plex users sync: instance_id=%s got 0 users from plex.tv (token may lack home access)",
            instance_id,
        )
        return
    await store_plex_users.replace_users(instance_id, users)
    log.debug(
        "Plex users sync: instance_id=%s synced %d users", instance_id, len(users)
    )


async def run_plex_users_sync_once(instance: dict, _session: AsyncSession) -> None:
    """Scheduled-task entry point: sync one Plex instance's users."""
    iid = instance_id_int(instance)
    if iid is None:
        return
    await _sync_one_instance(iid, instance["id"])


async def run_plex_users_sync() -> None:
    """Run one sync pass: list Plex instances, fetch users from plex.tv, upsert."""
    instances = await store_instances.list_instances()
    active = [
        inst
        for inst in instances
        if inst.get("is_configured")
        and inst.get("active", True)
        and (inst.get("service_type") or "") == "plex"
        and instance_id_int(inst) is not None
    ]

    async def _safe_sync(inst: dict) -> None:
        iid = instance_id_int(inst)
        if iid is None:
            return
        try:
            await _sync_one_instance(iid, inst["id"])
        except Exception as e:
            log.warning("Plex users sync failed for instance %s: %s", inst.get("id"), e)

    await asyncio.gather(*[_safe_sync(inst) for inst in active])
