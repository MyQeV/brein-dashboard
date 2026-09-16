"""Background sync of Jellyfin System/ActivityLog/Entries into jellyfin_activity_log_entries table."""

import asyncio
import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from brein import cache as brein_cache
from brein import config as brein_config
from brein.integrations.api import jellyfin as jellyfin_api
from brein.jobs._helpers import instance_id_int
from brein.store import jellyfin_activity_log as store_activity_log
from brein.store import jellyfin_dashboard_metrics as store_dashboard_metrics
from brein.store import jellyfin_playback_sessions as store_playback_sessions
from brein.store import instances as store_instances
from brein.store.metrics_helpers import _snapshot_rebuild_since

log = logging.getLogger(__name__)

PAGE_SIZE = 8000
CHUNK_DELAY_SECONDS = 0.5
MAX_ENTRIES_PER_RUN = 200_000


async def _sync_one_instance(instance_id: int, instance_id_for_config: Any) -> None:
    """Fetch activity log in chunks for one instance and upsert only new entries."""
    cfg = await store_instances.get_instance_connection_config(instance_id_for_config)
    if not cfg:
        return
    service_type, base_url, api_key = cfg
    if service_type != "jellyfin" or not base_url or not api_key:
        return

    last_entry_id = await store_activity_log.get_max_entry_id(instance_id)
    start_index = 0
    # Collected across the whole walk and written once at the end. Committing
    # per page looked cheaper, but the walk runs newest-first: on a first sync
    # page 1 committed and then page 2 failed, which advanced the watermark to
    # the newest id — so the next run saw nothing new on page 1, stopped, and
    # never asked for the older pages again. The gap was permanent and silent.
    pending: list[dict] = []

    while True:
        ok, items = await jellyfin_api.get_activity_log_entries(
            base_url, api_key, limit=PAGE_SIZE, start_index=start_index
        )
        if not ok:
            # A transient error is not the end of the log. Breaking here
            # recorded the run as a success, and the next run resumed from the
            # newest id already stored — so everything older stayed missing.
            raise RuntimeError(
                f"Jellyfin activity log fetch failed at start_index={start_index}"
            )
        if not items:
            break

        if last_entry_id is not None:
            new_items = [it for it in items if (it.get("Id") or 0) > last_entry_id]
            if not new_items:
                break
            pending.extend(new_items)
        else:
            pending.extend(items)

        if len(items) < PAGE_SIZE:
            break
        start_index += PAGE_SIZE
        if start_index >= MAX_ENTRIES_PER_RUN:
            # A server that ignores StartIndex returns the same newest page
            # forever; without this the loop never ends.
            log.warning(
                "Jellyfin activity log sync: instance_id=%s stopped at %d entries",
                instance_id,
                start_index,
            )
            break
        await asyncio.sleep(CHUNK_DELAY_SECONDS)

    if pending:
        await store_activity_log.upsert_entries(instance_id, pending)
        log.info(
            "Jellyfin activity log sync: instance_id=%s upserted %d entries",
            instance_id,
            len(pending),
        )


_last_snapshot_rebuild = 0.0
# What the next snapshot rebuild has to cover: the earliest local stat_date a
# session rebuild since the last one can have changed, or everything after a
# full session rebuild (and on the first pass after boot, when nothing is
# known). Every instance's sync feeds the same pair; the rebuild is global.
_snapshot_since: str | None = None
_snapshot_full_pending = True


def _note_snapshot_change(changed_at_utc: str | None) -> None:
    """Widen what the next snapshot rebuild covers; None means all of it."""
    global _snapshot_since, _snapshot_full_pending
    since = _snapshot_rebuild_since(changed_at_utc) if changed_at_utc else None
    if since is None:
        _snapshot_full_pending = True
    elif _snapshot_since is None or since < _snapshot_since:
        _snapshot_since = since


async def _rebuild_playback_sessions(instance_id: int) -> None:
    max_entry_id = await store_activity_log.get_max_entry_id(instance_id)
    if max_entry_id is None:
        return
    last_processed = await store_playback_sessions.get_last_processed_entry_id(
        instance_id
    )
    if last_processed is None:
        n = await store_playback_sessions.rebuild_sessions(
            instance_id=instance_id, since_date=None
        )
        _note_snapshot_change(None)
        if n:
            log.info(
                "Jellyfin playback sessions: instance_id=%s rebuilt %d sessions (full)",
                instance_id,
                n,
            )
        await store_playback_sessions.set_last_processed_entry_id(
            instance_id, max_entry_id
        )
    elif max_entry_id > last_processed:
        since_date = await store_activity_log.get_min_date_after_entry_id(
            instance_id, last_processed
        )
        if since_date is not None:
            n = await store_playback_sessions.rebuild_sessions(
                instance_id=instance_id, since_date=since_date
            )
            _note_snapshot_change(since_date)
            if n:
                log.info(
                    "Jellyfin playback sessions: instance_id=%s rebuilt %d sessions (since %s)",
                    instance_id,
                    n,
                    since_date,
                )
        await store_playback_sessions.set_last_processed_entry_id(
            instance_id, max_entry_id
        )


async def _rebuild_dashboard_snapshots() -> None:
    """Throttled global rebuild — caller may invoke per instance; gated by interval.

    Unthrottled, this ran a full DELETE + INSERT…SELECT over every snapshot
    table once per instance every 60 seconds, each pass rescanning all playback
    sessions. Emby's equivalent has always been gated this way. Now also
    incremental from the earliest day a session rebuild touched since the
    last pass, full when that is unknown, and skipped when nothing changed.
    """
    global _last_snapshot_rebuild, _snapshot_since, _snapshot_full_pending
    now = time.monotonic()
    if now - _last_snapshot_rebuild < brein_config.SNAPSHOT_REBUILD_INTERVAL_SECONDS:
        return
    if not _snapshot_full_pending and _snapshot_since is None:
        return
    # Stamped before the work, not after. Advancing only on success meant a
    # rebuild that keeps failing reran on every activity sync — the heaviest
    # query in the app, once a minute per instance — and a slow one let every
    # instance finishing during it queue another behind the lock. The Plex
    # path was fixed for this; these two were not.
    _last_snapshot_rebuild = now
    since_date = None if _snapshot_full_pending else _snapshot_since
    _snapshot_full_pending = False
    _snapshot_since = None
    try:
        await store_dashboard_metrics.rebuild_snapshots(since_date=since_date)
        # The merged cache is the one the dashboard reads. This used to
        # clear only the per-backend jellyfin cache, which the removed
        # /api/dashboard/*-metrics routes were the sole users of — so a
        # rebuild refreshed the snapshots and the dashboard went on
        # serving the stale merged payload until its TTL ran out.
        await brein_cache.clear_media_metrics_cache()
    except Exception as e:
        # The range this pass owed is lost with it; cover everything next time.
        _snapshot_full_pending = True
        log.warning("Jellyfin dashboard snapshot rebuild failed: %s", e)


async def run_jellyfin_activity_log_sync_once(
    instance: dict, _session: AsyncSession
) -> None:
    """Scheduled-task entry point: sync activity log + rebuild sessions for one Jellyfin instance."""
    iid = instance_id_int(instance)
    if iid is None:
        return
    await _sync_one_instance(iid, instance["id"])
    try:
        await _rebuild_playback_sessions(iid)
    except Exception as e:
        log.warning("Jellyfin session rebuild failed for instance %s: %s", iid, e)
    await _rebuild_dashboard_snapshots()


async def run_jellyfin_activity_log_sync() -> None:
    """Whole-pass sync (kept for one-shot callers): all instances, then global rebuilds."""
    instances = await store_instances.list_instances()
    jellyfin_instances = [
        inst
        for inst in instances
        if inst.get("is_configured")
        and inst.get("active", True)
        and (inst.get("service_type") or "") == "jellyfin"
    ]
    active_instances = [
        inst for inst in jellyfin_instances if instance_id_int(inst) is not None
    ]

    async def _safe_sync_entries(inst: dict) -> None:
        iid = instance_id_int(inst)
        if iid is None:
            return
        try:
            await _sync_one_instance(iid, inst["id"])
        except Exception as e:
            log.warning(
                "Jellyfin activity log sync failed for instance %s: %s",
                inst.get("id"),
                e,
            )

    await asyncio.gather(*[_safe_sync_entries(inst) for inst in active_instances])

    async def _rebuild_one(inst: dict) -> None:
        iid = instance_id_int(inst)
        if iid is None:
            return
        try:
            await _rebuild_playback_sessions(iid)
        except Exception as e:
            log.warning(
                "Jellyfin session rebuild failed for instance %s: %s", inst.get("id"), e
            )

    await asyncio.gather(*[_rebuild_one(inst) for inst in active_instances])
    await _rebuild_dashboard_snapshots()
