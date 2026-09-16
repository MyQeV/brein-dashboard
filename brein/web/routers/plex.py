"""Plex instance API endpoints."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from brein.integrations import plex as plex_integration
from brein.web import auth as web_auth
from brein.web.dependencies import require_instance_config
from brein.web.schemas import User

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]


async def _get_plex_config(instance_id: int) -> tuple[str, str]:
    _, base_url, api_key = await require_instance_config(
        instance_id, "plex", detail="Instance is not a Plex server"
    )
    return base_url, api_key


# Admin-only, matching the Emby routes these mirror: the stored Plex users
# carry e-mail addresses, and a raw /status/sessions payload carries each
# client's address. Both were readable by any signed-in account.
@router.get("/api/instances/{instance_id}/plex/sessions")
async def api_plex_sessions(instance_id: int, _user: AdminUser):
    """Return active Plex sessions for a given instance."""
    base_url, api_key = await _get_plex_config(instance_id)
    sessions = await plex_integration.get_sessions(base_url, api_key)
    if sessions is None:
        raise HTTPException(status_code=502, detail="Plex did not answer")
    return {"sessions": sessions}


@router.get("/api/instances/{instance_id}/plex/libraries")
async def api_plex_libraries(instance_id: int, _user: AdminUser):
    """Return Plex library sections for a given instance."""
    base_url, api_key = await _get_plex_config(instance_id)
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
    start: int = Query(0, ge=0),
    size: int = Query(100, ge=1, le=500),
):
    """Return Plex playback sessions recorded by Brein (live session polling).

    `total_size` counts the rows the filter matches, so a page past the end
    is empty rather than the whole list being cut at a fixed 500.
    """
    from brein.store import plex_playback_sessions as store_plex_playback

    await _get_plex_config(instance_id)
    rows, total = await asyncio.gather(
        store_plex_playback.get_entries(
            instance_id, user_id=account_id, limit=size, offset=start
        ),
        store_plex_playback.count_entries(instance_id, user_id=account_id),
    )
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
