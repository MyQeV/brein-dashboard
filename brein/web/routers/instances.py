"""App instances CRUD and test API."""

import logging
from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from brein import background
from brein.db import get_session_factory
from brein.jobs.emby_items_sync import run_emby_items_sync_for_instance
from brein.jobs.jellyfin_items_sync import run_jellyfin_items_sync_for_instance
from brein.jobs.plex_items_sync import run_plex_items_sync_for_instance
from brein.integrations.websockets import registry as ws_registry
from brein.jobs.scheduled_task_reconciler import reconcile as reconcile_scheduled_tasks
from brein.store import emby_items as store_emby_items
from brein.store import jellyfin_items as store_jellyfin_items
from brein.store import plex_items as store_plex_items
from brein.integrations import emby as emby_integration
from brein.integrations import plex as plex_integration
from brein.integrations.registry import test_service as integration_test_service
from brein.web import auth as web_auth
from brein.web import instance_settings
from brein.web.dependencies import require_instance_config
from brein.web.schemas import (
    InstanceCreateBody,
    InstanceProbeBody,
    InstanceUpdateBody,
    User,
)
from brein.store import service_config as store_service_config
from brein.store import instances as store_instances

log = logging.getLogger(__name__)

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]

# Per media server: has its library been scanned, and the one-off scan to
# queue when it has not.
_ITEMS_SYNC = {
    "emby": (store_emby_items.get_last_scan_date, run_emby_items_sync_for_instance),
    "jellyfin": (
        store_jellyfin_items.get_last_scan_date,
        run_jellyfin_items_sync_for_instance,
    ),
    "plex": (store_plex_items.get_last_scan_date, run_plex_items_sync_for_instance),
}


_CONNECTION_KEYS = ("host", "port", "external_url", "api_key_masked")


def _for_viewer(inst: dict, current_user: User) -> dict:
    """Viewers get what the instance pages render (id, label, app_url, ...);
    the connection fields are admin-only. app_url stays: the deep links need
    it, and with no external_url it is built from host and port anyway."""
    if current_user.is_admin:
        return inst
    return {k: v for k, v in inst.items() if k not in _CONNECTION_KEYS}


@router.get("/api/instances")
async def api_list_instances(current_user: CurrentUser):
    """List all app instances with is_configured."""
    instances = await store_instances.list_instances()
    return {"instances": [_for_viewer(i, current_user) for i in instances]}


def _connection_fields(host: str | None, api_key: str | None) -> tuple[str, str]:
    """Both or neither: a host without a key (or the reverse) cannot be tested."""
    host = (host or "").strip()
    api_key = (api_key or "").strip()
    if bool(host) != bool(api_key):
        raise HTTPException(
            status_code=400, detail="Host and API key are both required"
        )
    return host, api_key


@router.post("/api/instances/test")
async def api_probe_connection(body: InstanceProbeBody, current_user: AdminUser):
    """Try a connection before any instance exists.

    The add-app form refuses to save until this has passed, so nothing is
    stored that has never answered.
    """
    if body.service_type not in store_service_config.SERVICE_META:
        raise HTTPException(status_code=404, detail="Unknown service_type")
    host, api_key = _connection_fields(body.host, body.api_key)
    if not host:
        raise HTTPException(
            status_code=400, detail="Host and API key are both required"
        )
    base_url = store_instances.build_base_url(host, body.port, body.service_type)
    ok, message = await integration_test_service(body.service_type, base_url, api_key)
    return {"ok": ok, "message": message}


@router.post("/api/instances")
async def api_create_instance(body: InstanceCreateBody, current_user: AdminUser):
    """Create a new instance. Returns the new integer instance id.

    With a host and key the connection is tested first and a failure refuses
    the create: the form only saves after its own test passed, and this holds
    API callers to the same rule. Without them an unconfigured instance is
    created as before.
    """
    if body.service_type not in store_service_config.SERVICE_META:
        raise HTTPException(status_code=404, detail="Unknown service_type")
    host, api_key = _connection_fields(body.host, body.api_key)
    if host:
        base_url = store_instances.build_base_url(host, body.port, body.service_type)
        ok, message = await integration_test_service(
            body.service_type, base_url, api_key
        )
        if not ok:
            raise HTTPException(
                status_code=400, detail=f"Connection test failed: {message}"
            )
    try:
        new_id = await store_instances.create_instance(
            body.service_type,
            label=body.label,
            host=host,
            port=body.port,
            api_key=api_key,
            external_url=body.external_url or "",
            sort_order=body.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if body.active is False:
        await store_instances.update_instance(new_id, active=False)
    await _connection_changed(new_id)
    return {"id": new_id, "ok": True}


@router.get("/api/instances/{instance_id}")
async def api_get_instance(instance_id: int, current_user: CurrentUser):
    """Return one instance (api_key masked)."""
    inst = await store_instances.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")
    return _for_viewer(inst, current_user)


async def _record_server_info(
    instance_id: int, service_type: str, base_url: str, api_key: str
) -> None:
    """Store the media server's own id, which its deep links need.

    Emby and Jellyfin both report it as Id from System/Info, read here with
    the Emby client whose headers serve either server; Plex calls it the
    machineIdentifier. A failure is logged, never raised: the connection was
    saved or tested fine, this is bookkeeping on top.
    """
    try:
        if service_type in ("emby", "jellyfin"):
            ok, data = await emby_integration.get_system_info(base_url, api_key)
            if ok and data and isinstance(data.get("Id"), str):
                await store_instances.set_instance_server_info(
                    instance_id, media_server_id=data["Id"]
                )
        elif service_type == "plex":
            ok, data = await plex_integration.get_identity(base_url, api_key)
            if ok and data and data.get("machineIdentifier"):
                await store_instances.set_instance_server_info(
                    instance_id,
                    media_server_id=data["machineIdentifier"],
                    server_version=data.get("version") or "",
                )
    except Exception:
        log.exception("Could not record server info for instance %s", instance_id)


async def _connection_changed(instance_id: int) -> None:
    """What a saved connection sets in motion.

    Shared by create and update: record the media server's identity, queue
    the first library scan, refresh the scheduled-task names and restart the
    live listener with the new host and key.
    """
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if cfg:
        service_type, base_url, api_key = cfg
        if base_url and api_key:
            await _record_server_info(instance_id, service_type, base_url, api_key)
            sync = _ITEMS_SYNC.get(service_type)
            if sync and not await sync[0](instance_id):
                background.spawn(
                    sync[1](instance_id), f"{service_type}_items_sync[{instance_id}]"
                )
                log.info(
                    "%s items sync: scheduled initial sync for instance %s",
                    service_type,
                    instance_id,
                )
    # Scheduled-task names embed the instance label, so a rename leaves the
    # task list showing the old one until this runs. (Deletes need no
    # reconcile: scheduled_tasks.instance_id is ON DELETE CASCADE.)
    async with get_session_factory()() as s:
        await reconcile_scheduled_tasks(s)

    # The host, token or active flag may have just changed, and a listener
    # started at boot would keep using the old ones — reconnecting with a
    # stale token indefinitely, or polling a server that was deactivated.
    await ws_registry.restart(instance_id)


@router.put("/api/instances/{instance_id}")
async def api_put_instance(
    instance_id: int, body: InstanceUpdateBody, current_user: AdminUser
):
    """Update instance; omit or null keeps existing.

    A changed host, port or key is tested before it is stored, as on create:
    saving untested, the old connection was gone and the new one had never
    answered.
    """
    inst = await store_instances.get_instance(instance_id, mask_api_key=False)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")
    current = (
        (inst.get("host") or "").strip(),
        inst.get("port"),
        (inst.get("api_key") or "").strip(),
    )
    host = (body.host if body.host is not None else current[0]).strip()
    port = body.port if body.port is not None else current[1]
    api_key = (body.api_key if body.api_key is not None else current[2]).strip()
    if (host, port, api_key) != current:
        host, api_key = _connection_fields(host, api_key)
        if host:
            service_type = inst.get("service_type") or ""
            base_url = store_instances.build_base_url(host, port, service_type)
            ok, message = await integration_test_service(
                service_type, base_url, api_key
            )
            if not ok:
                raise HTTPException(
                    status_code=400, detail=f"Connection test failed: {message}"
                )
    try:
        await store_instances.update_instance(
            instance_id,
            host=body.host,
            port=body.port,
            api_key=body.api_key,
            label=body.label,
            external_url=body.external_url,
            active=body.active,
            sort_order=body.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _connection_changed(instance_id)
    return {"ok": True}


@router.delete("/api/instances/{instance_id}")
async def api_delete_instance(instance_id: int, current_user: AdminUser):
    """Delete an app instance."""
    inst = await store_instances.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")
    await store_instances.delete_instance(instance_id)
    # Otherwise its listener keeps reconnecting to a server that is gone, and
    # every frame it writes fails against the cascade-deleted rows.
    await ws_registry.stop(instance_id)
    return {"ok": True}


@router.get("/api/instances/{instance_id}/activity")
async def api_instance_activity(
    instance_id: int,
    current_user: AdminUser,
    min_date: str | None = Query(None),
    max_date: str | None = Query(None),
    user_id: str | None = Query(None),
    type: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
):
    """Stored activity for an instance, with the filters the UI needs.

    Reads Brein's own tables. The two endpoints that look like this one are
    not substitutes: /activitylog proxies the live Emby API rather than the
    stored log, and /plex/history has no date range or type filter.
    """
    instance = await store_instances.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    service_type = (instance.get("service_type") or "").lower()

    parsed_user_id: int | None = None
    if user_id:
        try:
            parsed_user_id = int(user_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="user_id must be an integer"
            ) from None

    if service_type == "plex":
        from brein.store import plex_playback_sessions as store_plex_playback
        from brein.store import plex_users as store_plex_users

        entries, distinct_types, users = await asyncio.gather(
            store_plex_playback.get_entries(
                instance_id,
                min_date=min_date,
                max_date=max_date,
                user_id=parsed_user_id,
                type_filter=type,
                limit=limit,
            ),
            store_plex_playback.get_distinct_types(instance_id),
            store_plex_users.get_users(instance_id),
        )
        user_options = [
            {
                "id": str(u["user_id"]),
                "name": u.get("title") or u.get("username") or str(u["user_id"]),
            }
            for u in users or []
            if u.get("user_id") is not None
        ]
    elif service_type in ("emby", "jellyfin"):
        from brein.store import emby_activity_log as store_activity_log
        from brein.store import emby_users as store_emby_users

        entries, distinct_types, users = await asyncio.gather(
            store_activity_log.get_entries(
                instance_id,
                min_date=min_date,
                max_date=max_date,
                user_id=parsed_user_id,
                type_filter=type,
                limit=limit,
            ),
            store_activity_log.get_distinct_types(instance_id),
            store_emby_users.get_users(instance_id),
        )
        user_options = [
            {
                "id": str(u["user_item_id"]),
                "name": u.get("name") or str(u["user_item_id"]),
            }
            for u in users or []
            if u.get("user_item_id") is not None
        ]
    else:
        return {"supported": False}

    names = {option["id"]: option["name"] for option in user_options}
    for entry in entries:
        raw = entry.get("user_id")
        entry["user_name"] = names.get(str(raw)) if raw is not None else None

    return {
        "entries": entries,
        "distinct_types": distinct_types,
        "users": user_options,
        "total": len(entries),
    }


@router.get("/api/instances/{instance_id}/user-dashboard")
async def api_instance_user_dashboard(
    instance_id: int,
    current_user: AdminUser,
    user_id: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    """Per-user watch statistics for an Emby instance.

    This existed only as a Jinja fragment, so none of it was reachable from an
    API client. Dates are resolved in the app timezone, not the caller's.
    """
    from datetime import date, timedelta

    from brein.config import get_local_date
    from brein.store import emby_users as store_emby_users
    from brein.store import metrics_users as store_metrics_users

    instance = await store_instances.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if (instance.get("service_type") or "").lower() != "emby":
        return {"supported": False}

    users = [
        u
        for u in (await store_emby_users.get_users(instance_id) or [])
        if not u.get("is_deleted")
    ]

    today = get_local_date()

    def _parse(value: str | None, fallback: date) -> date:
        if not value:
            return fallback
        try:
            return date.fromisoformat(value.strip())
        except (ValueError, TypeError):
            return fallback

    start_date = _parse(start, today - timedelta(days=29))
    end_date = _parse(end, today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    start_str, end_str = start_date.isoformat(), end_date.isoformat()

    selected = next(
        (u for u in users if str(u.get("user_item_id") or "") == (user_id or "")),
        None,
    )

    base = {
        "users": [
            {
                "id": str(u.get("user_item_id")),
                "name": u.get("name") or str(u.get("user_item_id")),
            }
            for u in users
        ],
        "selected_user_id": user_id or None,
        "start": start_str,
        "end": end_str,
        "today": today.isoformat(),
    }
    if selected is None:
        # No user chosen yet: the caller still needs the picker and the range.
        return {**base, "stats": None}

    uid = user_id or ""
    user_key = f"{instance_id}:{user_id}"
    async with get_session_factory()() as session:
        # Sequential, not gathered: an AsyncSession is not safe for
        # concurrent use, and running two queries on one session under gather
        # raises "_connection_for_bind() is already in progress".
        plays_rows = await store_metrics_users.get_plays_per_user(
            session, start_str, end_str, instance_id, [user_key]
        )
        watch_rows = await store_metrics_users.get_watch_time_per_user(
            session, start_str, end_str, instance_id, [user_key]
        )
        daily = await store_metrics_users.get_user_daily_watch_time(
            session, instance_id, uid, start_str, end_str
        )
        recent = await store_metrics_users.get_user_recent_items(
            session, instance_id, uid, limit=20
        )
        top_series = await store_metrics_users.get_user_top_items(
            session, instance_id, uid, start_str, end_str, "series"
        )
        top_movies = await store_metrics_users.get_user_top_items(
            session, instance_id, uid, start_str, end_str, "movies"
        )
        by_type = await store_metrics_users.get_user_watch_time_by_type(
            session, instance_id, uid, start_str, end_str
        )
        longest = await store_metrics_users.get_user_longest_session(
            session, instance_id, uid, start_str, end_str
        )
        weekday = await store_metrics_users.get_user_top_weekday(
            session, instance_id, uid, start_str, end_str
        )

    return {
        **base,
        "selected_user_name": selected.get("name"),
        "stats": {
            "plays": int(plays_rows[0]["plays"]) if plays_rows else 0,
            "watch_seconds": (int(watch_rows[0]["total_seconds"]) if watch_rows else 0),
            "last_activity": selected.get("last_activity_date"),
            "longest_session": longest,
            "top_weekday": weekday,
            "daily": daily,
            "recent_items": recent,
            "top_series": top_series,
            "top_movies": top_movies,
            "watch_by_type": by_type,
        },
    }


@router.get("/api/instances/{instance_id}/settings-info")
async def api_instance_settings_info(instance_id: int, current_user: AdminUser):
    """Live system info, health and host config for the Settings tab.

    Admin-only: it returns the target service's version, health messages and
    host configuration.
    """
    service_type, base_url, api_key = await require_instance_config(instance_id)
    return await instance_settings.load_settings_info(
        service_type, base_url, api_key, instance_id
    )


@router.post("/api/instances/{instance_id}/test")
async def api_test_instance(instance_id: int, current_user: AdminUser):
    """Test connection using instance's stored config (host/port/api_key)."""
    service_type, base_url, api_key = await require_instance_config(instance_id)
    ok, message = await integration_test_service(service_type, base_url, api_key)
    if ok:
        await _record_server_info(instance_id, service_type, base_url, api_key)
    return {"ok": ok, "message": message}


@router.get("/api/instances/{instance_id}/download-speed")
async def api_instance_download_speed(
    instance_id: int, current_user: CurrentUser
) -> dict:
    """Return current download speed (MB/s) for a single downloader instance."""
    from brein import cache as _cache
    from brein.extensions import load_extensions

    cache_key = f"dl_speed:{instance_id}"
    cached = await _cache.get_cached(cache_key)
    if cached is not None:
        return cached

    st, base_url, api_key = await require_instance_config(instance_id)
    adapter = load_extensions().downloaders.get(st)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Not a downloader instance")

    speed_mbps = 0.0
    try:
        ok, data = await adapter.status(base_url, api_key)
        speed_mbps = float(data.get("speed_mbps", 0.0)) if ok and data else 0.0
    except Exception:
        # Reported as 0.0 MB/s below. Log it so a persistently unreachable
        # downloader is visible rather than looking simply idle.
        log.warning(
            "Could not read download speed for instance %s", instance_id, exc_info=True
        )

    result = {"speed_mbps": round(speed_mbps, 2)}
    await _cache.set_cached(cache_key, result, ttl_seconds=10)
    return result
