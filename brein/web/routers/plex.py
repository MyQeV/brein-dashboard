"""Plex instance API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from brein.integrations import plex as plex_integration
from brein.store import instances as store_instances
from brein.web import auth as web_auth
from brein.web.schemas import User

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]


def _get_plex_config(cfg, instance_id: int):
    if not cfg:
        raise HTTPException(status_code=404, detail="Instance not found")
    service_type, base_url, api_key = cfg
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="Configure host and API key first")
    if service_type != "plex":
        raise HTTPException(status_code=400, detail="Instance is not a Plex server")
    return base_url, api_key


# Admin-only, matching the Emby routes these mirror: the stored Plex users
# carry e-mail addresses, and a raw /status/sessions payload carries each
# client's address. Both were readable by any signed-in account.
@router.get("/api/instances/{instance_id}/plex/sessions")
async def api_plex_sessions(instance_id: int, _user: AdminUser):
    """Return active Plex sessions for a given instance."""
    cfg = await store_instances.get_instance_connection_config(instance_id)
    base_url, api_key = _get_plex_config(cfg, instance_id)
    sessions = await plex_integration.get_sessions(base_url, api_key)
    if sessions is None:
        raise HTTPException(status_code=502, detail="Plex did not answer")
    return {"sessions": sessions}


@router.get("/api/instances/{instance_id}/plex/libraries")
async def api_plex_libraries(instance_id: int, _user: AdminUser):
    """Return Plex library sections for a given instance."""
    cfg = await store_instances.get_instance_connection_config(instance_id)
    base_url, api_key = _get_plex_config(cfg, instance_id)
    libraries = await plex_integration.get_libraries(base_url, api_key)
    return {"libraries": libraries}


@router.get("/api/instances/{instance_id}/plex/users")
async def api_plex_users(instance_id: int, _user: AdminUser):
    """Return stored Plex users for a given instance (synced from plex.tv)."""
    from brein.store import plex_users as store_plex_users

    users = await store_plex_users.get_users(instance_id)
    return {"users": users}


@router.get("/api/instances/{instance_id}/plex/history")
async def api_plex_history(
    instance_id: int,
    current_user: CurrentUser,
    account_id: int | None = None,
    start: int = 0,
    size: int = 100,
):
    """Return Plex playback sessions recorded by Brein (live session polling)."""
    from brein.store import plex_playback_sessions as store_plex_playback

    cfg = await store_instances.get_instance_connection_config(instance_id)
    _get_plex_config(cfg, instance_id)
    lim = max(1, min(start + max(1, size), 500))
    rows = await store_plex_playback.get_entries(
        instance_id,
        user_id=account_id,
        limit=lim,
    )
    total = await store_plex_playback.count_entries(instance_id)
    rows = rows[start : start + max(1, size)]
    history = [
        {
            "title": e.get("name") or "",
            "viewedAt": e.get("date"),
            "type": e.get("type"),
            "accountID": e.get("user_id"),
            "ratingKey": e.get("rating_key") or e.get("item_id"),
        }
        for e in rows
    ]
    return {"history": history, "total_size": total}
