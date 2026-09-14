"""Background sync of Emby library items (Movie, Series, Season, Episode) into emby_items table."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from brein.integrations.api import emby as emby_api
from brein.jobs._helpers import instance_id_int
from brein.store import emby_items as store_emby_items
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


# One library walk per instance at a time. Saving the instance form twice, or a
# scheduled pass landing on top of the initial one, otherwise ran two full
# walks against the same server concurrently.
_syncing: set[int] = set()


async def _sync_items_for_instance(
    instance_id: int, instance_id_for_config: Any
) -> None:
    """Fetch all items per type for one Emby instance and bulk upsert into emby_items."""
    cfg = await store_instances.get_instance_connection_config(instance_id_for_config)
    if not cfg:
        return
    service_type, base_url, api_key = cfg
    if service_type != "emby" or not base_url or not api_key:
        return

    if instance_id in _syncing:
        log.info(
            "Emby items sync: instance_id=%s already syncing, skipping", instance_id
        )
        return
    _syncing.add(instance_id)
    try:
        await _walk_item_types(instance_id, base_url, api_key)
    finally:
        _syncing.discard(instance_id)


async def _walk_item_types(instance_id: int, base_url: str, api_key: str) -> None:
    """Fetch every configured item type and upsert what comes back."""
    total_upserted = 0
    all_types_ok = True
    for item_type in ITEM_TYPES_TO_SYNC:
        try:
            ok, items = await emby_api.get_items_by_type(base_url, api_key, item_type)
            if not ok:
                all_types_ok = False
                log.warning(
                    "Emby items sync: failed to fetch %s for instance %s",
                    item_type,
                    instance_id,
                )
                continue
            if items:
                n = await store_emby_items.upsert_items_bulk(instance_id, items)
                total_upserted += n
                log.debug(
                    "Emby items sync: instance_id=%s type=%s upserted %d items",
                    instance_id,
                    item_type,
                    n,
                )
        except Exception as e:
            all_types_ok = False
            log.warning(
                "Emby items sync: error fetching %s for instance %s: %s",
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
        await store_emby_items.set_last_scan_date(instance_id, now)
        log.info(
            "Emby items sync: instance_id=%s upserted %d items total",
            instance_id,
            total_upserted,
        )


async def run_emby_items_sync_once(instance: dict, _session: AsyncSession) -> None:
    """Scheduled-task entry point: sync items for one Emby instance."""
    iid = instance_id_int(instance)
    if iid is None:
        return
    await _sync_items_for_instance(iid, instance["id"])


async def run_emby_items_sync() -> None:
    """Run one sync pass: list Emby instances, fetch items per type, bulk upsert."""
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
            await _sync_items_for_instance(iid, inst["id"])
        except Exception as e:
            log.warning("Emby items sync failed for instance %s: %s", inst.get("id"), e)

    await asyncio.gather(*[_safe_sync(inst) for inst in active])


async def run_emby_items_sync_for_instance(
    instance_id: int, delay_seconds: float = INITIAL_SYNC_DELAY_SECONDS
) -> None:
    """One-off sync for a single instance, with optional delay."""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    instances = await store_instances.list_instances()
    for inst in instances:
        iid = instance_id_int(inst)
        if iid == instance_id:
            if not inst.get("active", True):
                log.info(
                    "Emby items sync: skipping initial sync for inactive instance %s",
                    instance_id,
                )
                return
            await _sync_items_for_instance(iid, inst["id"])
            return
