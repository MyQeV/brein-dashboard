"""Background sync of Jellyfin library items (Movie, Series, Season, Episode) into jellyfin_items table."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from brein.integrations.api import jellyfin as jellyfin_api
from brein.jobs._helpers import instance_id_int
from brein.store import jellyfin_items as store_jellyfin_items
from brein.store import instances as store_instances

log = logging.getLogger(__name__)

ITEM_TYPES_TO_SYNC = [
    "Movie",
    "Series",
    "Season",
    "Episode",
    "LiveTvChannel",
    "Program",
]

TYPE_DELAY_SECONDS = 1.0
INITIAL_SYNC_DELAY_SECONDS = 10.0


async def _sync_items_for_instance(
    instance_id: int, instance_id_for_config: Any
) -> None:
    """Fetch all items per type for one Jellyfin instance and bulk upsert into jellyfin_items."""
    cfg = await store_instances.get_instance_connection_config(instance_id_for_config)
    if not cfg:
        return
    service_type, base_url, api_key = cfg
    if service_type != "jellyfin" or not base_url or not api_key:
        return

    total_upserted = 0
    all_types_ok = True
    for item_type in ITEM_TYPES_TO_SYNC:
        try:
            ok, items = await jellyfin_api.get_items_by_type(
                base_url, api_key, item_type
            )
            if not ok:
                all_types_ok = False
                log.warning(
                    "Jellyfin items sync: failed to fetch %s for instance %s",
                    item_type,
                    instance_id,
                )
                continue
            if items:
                n = await store_jellyfin_items.upsert_items_bulk(instance_id, items)
                total_upserted += n
                log.debug(
                    "Jellyfin items sync: instance_id=%s type=%s upserted %d items",
                    instance_id,
                    item_type,
                    n,
                )
        except Exception as e:
            all_types_ok = False
            log.warning(
                "Jellyfin items sync: error fetching %s for instance %s: %s",
                item_type,
                instance_id,
                e,
            )
        await asyncio.sleep(TYPE_DELAY_SECONDS)

    # Only a complete pass counts as a scan: `last_scan_date` is what tells
    # instances.py an instance no longer needs its initial sync, so recording a
    # partial pass disabled that recovery path for good.
    if total_upserted and all_types_ok:
        now = datetime.now(timezone.utc).isoformat()
        await store_jellyfin_items.set_last_scan_date(instance_id, now)
        log.info(
            "Jellyfin items sync: instance_id=%s upserted %d items total",
            instance_id,
            total_upserted,
        )


async def run_jellyfin_items_sync_once(instance: dict, _session: AsyncSession) -> None:
    """Scheduled-task entry point: sync items for one Jellyfin instance."""
    iid = instance_id_int(instance)
    if iid is None:
        return
    await _sync_items_for_instance(iid, instance["id"])


async def run_jellyfin_items_sync() -> None:
    """Run one sync pass: list Jellyfin instances, fetch items per type, bulk upsert."""
    instances = await store_instances.list_instances()
    active = [
        inst
        for inst in instances
        if inst.get("is_configured")
        and inst.get("active", True)
        and (inst.get("service_type") or "") == "jellyfin"
        and instance_id_int(inst) is not None
    ]

    async def _safe_sync(inst: dict) -> None:
        iid = instance_id_int(inst)
        if iid is None:
            return
        try:
            await _sync_items_for_instance(iid, inst["id"])
        except Exception as e:
            log.warning(
                "Jellyfin items sync failed for instance %s: %s", inst.get("id"), e
            )

    await asyncio.gather(*[_safe_sync(inst) for inst in active])


async def run_jellyfin_items_sync_for_instance(
    instance_id: int, delay_seconds: float = INITIAL_SYNC_DELAY_SECONDS
) -> None:
    """One-off sync for a single Jellyfin instance, with optional delay."""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    instances = await store_instances.list_instances()
    for inst in instances:
        iid = instance_id_int(inst)
        if iid == instance_id:
            if not inst.get("active", True):
                log.info(
                    "Jellyfin items sync: skipping initial sync for inactive instance %s",
                    instance_id,
                )
                return
            await _sync_items_for_instance(iid, inst["id"])
            return
