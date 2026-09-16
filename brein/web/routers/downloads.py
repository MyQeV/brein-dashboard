"""One JSON API across every registered download client.

The existing per-service routes return rendered HTML — badges and table
fragments — so none of this was reachable from an API client. These endpoints
return normalized JSON with raw bytes; see the downloader adapters for the
shaping.
"""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from brein.extensions import UnsupportedOperation, load_extensions
from brein.integrations.api import sabnzbd as sabnzbd_api
from brein.web import auth as web_auth
from brein.web.dependencies import require_instance_config
from brein.web.schemas import User

router = APIRouter(prefix="/api/instances/{instance_id}/downloads", tags=["downloads"])

CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]

UNREACHABLE = "Could not reach the download client"


class PauseTimedBody(BaseModel):
    minutes: int = Field(ge=1, le=24 * 60)


class MoveBody(BaseModel):
    position: int = Field(ge=0)


class SortBody(BaseModel):
    field: str = Field(pattern="^(avg_age|name|size)$")
    direction: str = Field(pattern="^(asc|desc)$")


class SpeedLimitBody(BaseModel):
    """SABnzbd takes a percentage of its configured maximum; other downloaders
    take a rate in bytes per second. The unit conversion each client needs
    happens in its adapter, so this value is always in the unit the client's
    own UI shows."""

    value: int = Field(ge=0)


async def _config(instance_id: int) -> tuple[str, str, str, Any]:
    service_type, base_url, api_key = await require_instance_config(instance_id)
    adapter = load_extensions().downloaders.get(service_type)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Not a download client")
    return service_type, base_url, api_key, adapter


@router.get("/queue")
async def get_queue(instance_id: int, _user: CurrentUser) -> dict[str, Any]:
    service_type, base_url, api_key, adapter = await _config(instance_id)
    ok, data = await adapter.queue(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {
        "service_type": service_type,
        "capabilities": asdict(adapter.capabilities),
        **data,
    }


@router.get("/history")
async def get_history(instance_id: int, _user: CurrentUser) -> dict[str, Any]:
    service_type, base_url, api_key, adapter = await _config(instance_id)
    ok, items = await adapter.history(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {
        "service_type": service_type,
        "capabilities": asdict(adapter.capabilities),
        "items": items,
    }


@router.post("/pause")
async def pause(instance_id: int, _user: AdminUser) -> dict[str, Any]:
    _service_type, base_url, api_key, adapter = await _config(instance_id)
    try:
        ok, _msg = await adapter.pause(base_url, api_key, None)
    except UnsupportedOperation as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True, "paused": True}


@router.post("/resume")
async def resume(instance_id: int, _user: AdminUser) -> dict[str, Any]:
    _service_type, base_url, api_key, adapter = await _config(instance_id)
    try:
        ok, _msg = await adapter.resume(base_url, api_key, None)
    except UnsupportedOperation as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True, "paused": False}


@router.put("/speed-limit")
async def set_speed_limit(
    instance_id: int, body: SpeedLimitBody, _user: AdminUser
) -> dict[str, Any]:
    _service_type, base_url, api_key, adapter = await _config(instance_id)
    ok, _ = await adapter.set_speed_limit(base_url, api_key, body.value)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True, "value": body.value}


@router.post("/items/{item_id}/pause")
async def pause_item(
    instance_id: int, item_id: str, _user: AdminUser
) -> dict[str, Any]:
    _service_type, base_url, api_key, adapter = await _config(instance_id)
    try:
        ok, _msg = await adapter.pause(base_url, api_key, item_id)
    except UnsupportedOperation as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.post("/items/{item_id}/resume")
async def resume_item(
    instance_id: int, item_id: str, _user: AdminUser
) -> dict[str, Any]:
    _service_type, base_url, api_key, adapter = await _config(instance_id)
    try:
        ok, _msg = await adapter.resume(base_url, api_key, item_id)
    except UnsupportedOperation as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.delete("/items/{item_id}")
async def delete_item(
    instance_id: int, item_id: str, _user: AdminUser
) -> dict[str, Any]:
    _service_type, base_url, api_key, adapter = await _config(instance_id)
    try:
        ok, _msg = await adapter.delete(base_url, api_key, item_id, remove_files=False)
    except UnsupportedOperation as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


def _require_sabnzbd(service_type: str, action: str) -> None:
    """These operations exist only in SABnzbd's API."""
    if service_type != "sabnzbd":
        raise HTTPException(
            status_code=400, detail=f"{action} is only supported for SABnzbd"
        )


@router.post("/pause-timed")
async def pause_timed(
    instance_id: int, body: PauseTimedBody, _user: AdminUser
) -> dict[str, Any]:
    """Pause the queue for a set number of minutes, then resume by itself."""
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Timed pause")
    ok, _ = await sabnzbd_api.pause_timed(base_url, api_key, body.minutes)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True, "minutes": body.minutes}


@router.post("/items/{item_id}/move")
async def move_item(
    instance_id: int, item_id: str, body: MoveBody, _user: AdminUser
) -> dict[str, Any]:
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Reordering the queue")
    ok, _ = await sabnzbd_api.move_nzo(base_url, api_key, item_id, body.position)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.post("/sort")
async def sort_queue(
    instance_id: int, body: SortBody, _user: AdminUser
) -> dict[str, Any]:
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Sorting the queue")
    ok, _ = await sabnzbd_api.sort_queue(base_url, api_key, body.field, body.direction)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.post("/history/{item_id}/retry")
async def retry_history_item(
    instance_id: int, item_id: str, _user: AdminUser
) -> dict[str, Any]:
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Retrying a download")
    ok, _ = await sabnzbd_api.retry_history(base_url, api_key, item_id)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.post("/history/retry-all")
async def retry_all_history(instance_id: int, _user: AdminUser) -> dict[str, Any]:
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Retrying all failed downloads")
    ok, _ = await sabnzbd_api.retry_all_history(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.post("/history/{item_id}/mark-completed")
async def mark_history_completed(
    instance_id: int, item_id: str, _user: AdminUser
) -> dict[str, Any]:
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Marking a download completed")
    ok, _ = await sabnzbd_api.mark_completed(base_url, api_key, item_id)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.delete("/history/{item_id}")
async def delete_history_item(
    instance_id: int, item_id: str, _user: AdminUser
) -> dict[str, Any]:
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Deleting history")
    ok, _ = await sabnzbd_api.delete_history(base_url, api_key, item_id)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}


@router.delete("/history")
async def purge_history(instance_id: int, _user: AdminUser) -> dict[str, Any]:
    """Remove every history entry. Not reversible."""
    service_type, base_url, api_key, _adapter = await _config(instance_id)
    _require_sabnzbd(service_type, "Purging history")
    ok, _ = await sabnzbd_api.purge_history(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return {"ok": True}
