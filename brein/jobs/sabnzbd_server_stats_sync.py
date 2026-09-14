"""Background sync: SABnzbd server_stats snapshots for KPIs and daily charts."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from brein.integrations.api import sabnzbd as sabnzbd_api
from brein.jobs._helpers import instance_id_int
from brein.store import instances as store_instances
from brein.store import sabnzbd_stats as store_sabnzbd_stats

log = logging.getLogger(__name__)


async def _sync_one_instance(instance_id: int, inst_id: object) -> None:
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        return
    service_type, base_url, api_key = cfg
    if service_type != "sabnzbd" or not base_url or not api_key:
        return
    ok, data = await sabnzbd_api.get_server_stats(base_url, api_key)
    if not ok or not isinstance(data, dict):
        # Raised rather than returned, so the task row shows the failure. A
        # quiet return recorded success while no snapshot was written.
        raise RuntimeError(f"SABnzbd server_stats fetch failed for instance {inst_id}")
    await store_sabnzbd_stats.insert_snapshot(instance_id, data)
    log.debug(
        "SABnzbd server_stats sync: stored snapshot for instance_id=%s",
        instance_id,
    )


async def run_sabnzbd_server_stats_sync_once(
    instance: dict, _session: AsyncSession
) -> None:
    """Scheduled-task entry point: snapshot stats for one SABnzbd instance."""
    iid = instance_id_int(instance)
    if iid is None:
        return
    await _sync_one_instance(iid, instance["id"])


async def run_sabnzbd_server_stats_sync() -> None:
    """Fetch server_stats for each configured SABnzbd instance and persist."""
    instances = await store_instances.list_instances()
    active = [
        inst
        for inst in instances
        if inst.get("is_configured")
        and inst.get("active", True)
        and (inst.get("service_type") or "") == "sabnzbd"
        and instance_id_int(inst) is not None
    ]

    async def _safe(inst: dict) -> None:
        iid = instance_id_int(inst)
        if iid is None:
            return
        try:
            await _sync_one_instance(iid, inst.get("id"))
        except Exception as e:
            log.warning(
                "SABnzbd server_stats sync failed for instance %s: %s",
                inst.get("id"),
                e,
            )

    await asyncio.gather(*[_safe(inst) for inst in active])
