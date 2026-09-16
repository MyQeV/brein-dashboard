"""Emby instance API (users, libraries, activity log)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from brein.integrations import emby as emby_integration
from brein.integrations.api import jellyfin as jellyfin_integration
from brein.web import auth as web_auth
from brein.web.dependencies import require_instance_config
from brein.web.schemas import (
    BulkStatusRequest,
    UpdateUserRequest,
    User,
    UsersPolicyBody,
)

router = APIRouter()
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]
WebUser = Annotated[User, Depends(web_auth.get_current_user_cookie_or_bearer)]
WebAdmin = Annotated[User, Depends(web_auth.get_current_admin_user_cookie_or_bearer)]

MEDIA_SERVER_TYPES = ("emby", "jellyfin")


def _media_integration(service_type: str):
    """Return the right integration module for the given service type."""
    return jellyfin_integration if service_type == "jellyfin" else emby_integration


async def _require_media_config(
    instance_id: int, *, detail: str, status_code: int
) -> tuple[str, str, str]:
    """An Emby or Jellyfin instance with a connection, or the route's own error."""
    return await require_instance_config(
        instance_id, MEDIA_SERVER_TYPES, detail=detail, status_code=status_code
    )


@router.get("/api/instances/{instance_id}/users")
async def api_instance_users(instance_id: int, current_user: AdminUser):
    """List users and libraries for Emby/Jellyfin instance. Unsupported types return supported: false."""
    service_type, base_url, api_key = await require_instance_config(instance_id)
    if service_type not in MEDIA_SERVER_TYPES:
        return {"supported": False}
    integration = _media_integration(service_type)
    ok_users, raw_users = await integration.get_users(base_url, api_key)
    ok_folders, raw_folders = await integration.get_media_folders(base_url, api_key)
    if not ok_users or raw_users is None:
        raise HTTPException(status_code=502, detail="Failed to fetch users")
    libraries = []
    if ok_folders and raw_folders:
        for it in raw_folders:
            if isinstance(it, dict) and it.get("Id") is not None:
                # `id` is the one a user policy's EnabledFolders references,
                # which is not the same field on both servers: Jellyfin's Id
                # is already that value, while Emby numbers its library views
                # (4, 526, …) and stores the Guid in the policy. Keying the
                # list on Id therefore matched nothing on Emby, and the users
                # table printed raw GUIDs where library names belong.
                internal_id = str(it["Id"])
                guid = it.get("Guid")
                libraries.append(
                    {
                        "id": str(guid) if guid else internal_id,
                        "name": (it.get("Name") or internal_id),
                        "internal_id": internal_id,
                        "server_id": it.get("ServerId"),
                        "guid": guid,
                        "type": it.get("Type"),
                        "collection_type": it.get("CollectionType"),
                    }
                )
    users = []
    for u in raw_users:
        if not isinstance(u, dict):
            continue
        policy = u.get("Policy") or {}
        if not isinstance(policy, dict):
            policy = {}
        enabled = policy.get("EnabledFolders")
        if not isinstance(enabled, list):
            enabled = []
        users.append(
            {
                "id": str(u.get("Id", "")),
                "name": (u.get("Name") or ""),
                "is_disabled": bool(policy.get("IsDisabled")),
                "is_administrator": bool(policy.get("IsAdministrator")),
                "enable_all_folders": bool(policy.get("EnableAllFolders")),
                "enabled_folder_ids": [str(x) for x in enabled],
                "last_login_date": u.get("LastLoginDate"),
                "last_activity_date": u.get("LastActivityDate"),
                "primary_image_tag": u.get("PrimaryImageTag"),
                "user_item_id": u.get("Id"),
                "enable_live_tv": bool(policy.get("EnableLiveTvAccess")),
                "max_simultaneous_streams": int(
                    policy.get("SimultaneousStreamLimit") or 0
                ),
            }
        )
    return {"users": users, "libraries": libraries}


@router.get("/api/instances/{instance_id}/libraries")
async def api_instance_libraries(instance_id: int, current_user: AdminUser):
    """List SelectableMediaFolders for Emby instance. Unsupported types return supported: false."""
    service_type, base_url, api_key = await require_instance_config(instance_id)
    if service_type not in MEDIA_SERVER_TYPES:
        return {"supported": False}
    ok_folders, raw_folders = await _media_integration(service_type).get_media_folders(
        base_url, api_key
    )
    if not ok_folders or raw_folders is None:
        raise HTTPException(status_code=502, detail="Failed to fetch libraries")
    libraries = []
    for it in raw_folders:
        if isinstance(it, dict) and it.get("Id") is not None:
            libraries.append(
                {
                    "id": str(it["Id"]),
                    "name": (it.get("Name") or str(it["Id"])),
                    "server_id": it.get("ServerId"),
                    "guid": it.get("Guid"),
                    "type": it.get("Type"),
                    "collection_type": it.get("CollectionType"),
                }
            )
    return {"supported": True, "libraries": libraries}


@router.post("/api/instances/{instance_id}/users/policy")
async def api_instance_users_policy(
    instance_id: int, body: UsersPolicyBody, current_user: AdminUser
):
    """Bulk update library access for selected users (Emby only)."""
    service_type, base_url, api_key = await _require_media_config(
        instance_id, detail="Not supported for this app", status_code=404
    )
    if not body.user_ids:
        raise HTTPException(status_code=400, detail="user_ids required")
    updated = 0
    errors = []
    for uid in body.user_ids:
        ok, msg = await _media_integration(service_type).update_user_policy(
            base_url,
            api_key,
            uid,
            enable_all_folders=body.enable_all_folders,
            enabled_folder_ids=body.enabled_folder_ids,
        )
        if ok:
            updated += 1
        else:
            errors.append({"user_id": uid, "message": msg})
    return {"updated": updated, "errors": errors}


@router.get("/api/instances/{instance_id}/users/{user_id}")
async def api_instance_user_detail(
    instance_id: int, user_id: str, current_user: AdminUser
):
    """Return full user details for Emby (for user detail view)."""
    service_type, base_url, api_key = await _require_media_config(
        instance_id, detail="Not supported for this app", status_code=404
    )
    ok, user = await _media_integration(service_type).get_user_by_id(
        base_url, api_key, user_id
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to fetch user")
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/api/instances/{instance_id}/activitylog")
async def api_instance_activitylog(
    instance_id: int,
    current_user: AdminUser,
    limit: int = Query(50, ge=1, le=200),
    start_index: int = Query(0, ge=0),
):
    """Return Emby ActivityLog entries for the instance. 404 if not Emby.

    `count` is the size of this page: the client drops the server's
    TotalRecordCount, so the number of entries overall is not known here.
    """
    service_type, base_url, api_key = await _require_media_config(
        instance_id, detail="Not supported for this app", status_code=404
    )
    ok, items = await _media_integration(service_type).get_activity_log_entries(
        base_url, api_key, limit=limit, start_index=start_index
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to fetch activity log")
    return {"items": items, "count": len(items)}


@router.post("/api/instances/{instance_id}/users/bulk-status")
async def api_instance_users_bulk_status(
    instance_id: int, body: BulkStatusRequest, current_user: AdminUser
):
    """Bulk set active/inactive for selected Emby users."""
    service_type, base_url, api_key = await _require_media_config(
        instance_id, detail="Not supported for this app", status_code=404
    )
    if not body.user_ids:
        raise HTTPException(status_code=400, detail="user_ids required")
    updated = 0
    errors = []
    for uid in body.user_ids:
        ok, msg = await _media_integration(service_type).update_user_policy(
            base_url, api_key, uid, is_disabled=body.is_disabled
        )
        if ok:
            updated += 1
        else:
            errors.append({"user_id": uid, "message": msg})
    return {"updated": updated, "errors": errors}


@router.patch("/api/instances/{instance_id}/users/{user_id}")
async def api_instance_user_update(
    instance_id: int, user_id: str, body: UpdateUserRequest, current_user: AdminUser
):
    """Update Emby user info (name, password, policy fields)."""
    service_type, base_url, api_key = await _require_media_config(
        instance_id, detail="Not supported for this app", status_code=404
    )
    if body.name is not None:
        ok, msg = await _media_integration(service_type).update_user(
            base_url, api_key, user_id, body.name
        )
        if not ok:
            raise HTTPException(status_code=502, detail=f"Name update failed: {msg}")
    if body.new_password is not None:
        ok, msg = await _media_integration(service_type).update_user_password(
            base_url, api_key, user_id, body.new_password
        )
        if not ok:
            raise HTTPException(
                status_code=502, detail=f"Password update failed: {msg}"
            )
    has_policy_update = any(
        v is not None
        for v in (
            body.is_administrator,
            body.enable_live_tv,
            body.enable_live_tv_management,
            body.max_simultaneous_streams,
            body.enable_all_folders,
            body.enabled_folder_ids,
            body.is_hidden,
            body.is_hidden_remotely,
            body.is_hidden_from_unused_devices,
            body.is_disabled,
            body.remote_client_bitrate_limit,
            body.auto_remote_quality,
        )
    )
    if has_policy_update:
        ok, msg = await _media_integration(service_type).update_user_policy(
            base_url,
            api_key,
            user_id,
            is_administrator=body.is_administrator,
            enable_live_tv=body.enable_live_tv,
            enable_live_tv_management=body.enable_live_tv_management,
            max_simultaneous_streams=body.max_simultaneous_streams,
            enable_all_folders=body.enable_all_folders,
            enabled_folder_ids=body.enabled_folder_ids,
            is_hidden=body.is_hidden,
            is_hidden_remotely=body.is_hidden_remotely,
            is_hidden_from_unused_devices=body.is_hidden_from_unused_devices,
            is_disabled=body.is_disabled,
            remote_client_bitrate_limit=body.remote_client_bitrate_limit,
            auto_remote_quality=body.auto_remote_quality,
        )
        if not ok:
            raise HTTPException(status_code=502, detail=f"Policy update failed: {msg}")
    return {"ok": True}


@router.get("/api/instances/{instance_id}/media/ping")
async def api_instance_media_ping(instance_id: int, current_user: WebUser):
    """Lightweight reachability check (GET System/Info)."""
    service_type, base_url, api_key = await _require_media_config(
        instance_id, detail="Not an Emby or Jellyfin instance", status_code=400
    )
    ok, message = await _media_integration(service_type).test_connection(
        base_url, api_key
    )
    return {"ok": ok, "message": message}


@router.post("/api/instances/{instance_id}/media/system/restart")
async def api_instance_media_system_restart(instance_id: int, current_user: WebAdmin):
    """POST System/Restart on Emby or Jellyfin. Admin only."""
    service_type, base_url, api_key = await _require_media_config(
        instance_id, detail="Not an Emby or Jellyfin instance", status_code=400
    )
    ok, msg = await _media_integration(service_type).post_system_restart(
        base_url, api_key
    )
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Restart failed")
    return {"ok": True, "message": msg}
