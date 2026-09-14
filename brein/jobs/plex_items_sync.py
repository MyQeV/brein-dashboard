"""Background sync of Plex library items (movie, show, season, episode) into plex_items."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from brein.integrations.api import plex as plex_api
from brein.jobs._helpers import instance_id_int
from brein.store import instances as store_instances
from brein.store import plex_items as store_plex_items

log = logging.getLogger(__name__)

PAGE_DELAY_SECONDS = 0.2
TYPE_DELAY_SECONDS = 1.0
DEFAULT_PAGE_SIZE = 100
INITIAL_SYNC_DELAY_SECONDS = 10.0


async def _sync_items_for_instance(
    instance_id: int, instance_id_for_config: Any
) -> None:
    cfg = await store_instances.get_instance_connection_config(instance_id_for_config)
    if not cfg:
        return
    service_type, base_url, api_key = cfg
    if service_type != "plex" or not base_url or not api_key:
        return

    ok_id, identity = await plex_api.get_identity(base_url, api_key)
    server_id = ""
    if ok_id and identity:
        server_id = str(identity.get("machineIdentifier") or "").strip()
    elif not ok_id:
        # The upsert writes server_id unconditionally, so carrying an empty
        # one through a failed /identity blanked the column on every row in
        # the library. One timeout should not damage what is already stored.
        raise RuntimeError(f"Plex identity fetch failed for instance {instance_id}")

    now = datetime.now(timezone.utc).isoformat()
    total_upserted = 0
    all_types_ok = True

    for media_type in plex_api.PLEX_LIBRARY_MEDIA_TYPES:
        start = 0
        try:
            while True:
                items, total_size = await plex_api.get_library_all_items_page(
                    base_url,
                    api_key,
                    media_type,
                    start,
                    DEFAULT_PAGE_SIZE,
                )
                if items is None:
                    # The request failed. Breaking here as if the library had
                    # ended is what let a partial pass stamp last_scan_date:
                    # the client returned [] for a timeout and for the end of
                    # the library alike, so all_types_ok never tripped.
                    all_types_ok = False
                    log.warning(
                        "Plex items sync: page failed type=%s instance %s start=%s",
                        media_type,
                        instance_id,
                        start,
                    )
                    break
                if not items:
                    break
                rows: list[dict[str, Any]] = []
                for m in items:
                    if not isinstance(m, dict):
                        continue
                    row = store_plex_items.row_from_plex_metadata(
                        instance_id, m, server_id, now
                    )
                    if row:
                        rows.append(row)
                if rows:
                    n = await store_plex_items.upsert_items_bulk(instance_id, rows)
                    total_upserted += n
                    log.debug(
                        "Plex items sync: instance_id=%s type=%s page start=%s upserted %s",
                        instance_id,
                        media_type,
                        start,
                        n,
                    )
                batch_len = len(items)
                start += batch_len
                if total_size is not None and start >= total_size:
                    break
                if batch_len < DEFAULT_PAGE_SIZE:
                    break
                await asyncio.sleep(PAGE_DELAY_SECONDS)
        except Exception as e:
            all_types_ok = False
            log.warning(
                "Plex items sync: error type=%s instance %s: %s",
                media_type,
                instance_id,
                e,
            )
        await asyncio.sleep(TYPE_DELAY_SECONDS)

    # Only a complete pass counts as a scan, as the Emby job already had it:
    # `last_scan_date` is what tells instances.py an instance no longer needs
    # its initial sync, so stamping a partial pass disabled that recovery.
    if total_upserted and all_types_ok:
        await store_plex_items.set_last_scan_date(instance_id, now)
        log.info(
            "Plex items sync: instance_id=%s upserted %d items total",
            instance_id,
            total_upserted,
        )


async def run_plex_items_sync_once(instance: dict, _session: AsyncSession) -> None:
    """Scheduled-task entry point: sync items for one Plex instance."""
    iid = instance_id_int(instance)
    if iid is None:
        return
    await _sync_items_for_instance(iid, instance["id"])


async def run_plex_items_sync() -> None:
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
            await _sync_items_for_instance(iid, inst["id"])
        except Exception as e:
            log.warning("Plex items sync failed for instance %s: %s", inst.get("id"), e)

    await asyncio.gather(*[_safe_sync(inst) for inst in active])


async def run_plex_items_sync_for_instance(
    instance_id: int, delay_seconds: float = INITIAL_SYNC_DELAY_SECONDS
) -> None:
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    instances = await store_instances.list_instances()
    for inst in instances:
        iid = instance_id_int(inst)
        if iid == instance_id:
            if not inst.get("active", True):
                log.info(
                    "Plex items sync: skipping initial sync for inactive instance %s",
                    instance_id,
                )
                return
            await _sync_items_for_instance(iid, inst["id"])
            return
