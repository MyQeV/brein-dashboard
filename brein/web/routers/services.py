"""Services and service-types API."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from brein.extensions import load_extensions
from brein.integrations.registry import test_service as integration_test_service
from brein.web import auth as web_auth
from brein.web.schemas import ServiceConfigBody, User
from brein.store import service_config as store_service_config

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]


@router.get("/api/services")
async def api_list_services(current_user: CurrentUser):
    """List known services with has_config."""
    return {"services": await store_service_config.list_services()}


@router.get("/api/services/{service_id}/config")
async def api_get_service_config(service_id: str, current_user: AdminUser):
    """Return stored base_url and masked api_key for a service.

    Admin-only: this exposes where a service lives, and its sibling PUT is
    already admin-gated.
    """
    if service_id not in store_service_config.SERVICE_META:
        raise HTTPException(status_code=404, detail="Unknown service")
    cfg = await store_service_config.get_config(service_id)
    if not cfg:
        return {"base_url": "", "api_key_masked": ""}
    key = cfg.get("api_key") or ""
    masked = "***" + key[-4:] if len(key) > 4 else "***"
    return {"base_url": cfg.get("base_url") or "", "api_key_masked": masked}


@router.put("/api/services/{service_id}/config")
async def api_put_service_config(
    service_id: str, body: ServiceConfigBody, current_user: AdminUser
):
    """Save base_url and api_key for a service. Empty api_key keeps existing key."""
    if service_id not in store_service_config.SERVICE_META:
        raise HTTPException(status_code=404, detail="Unknown service")
    base_url = (body.base_url or "").strip()
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400, detail="base_url must be a valid HTTP(S) URL"
        )
    api_key = body.api_key or ""
    if not api_key:
        existing = await store_service_config.get_config(service_id)
        if existing and existing.get("api_key"):
            api_key = existing["api_key"]
    await store_service_config.set_config(service_id, base_url, api_key)
    return {"ok": True}


@router.post("/api/services/{service_id}/test")
async def api_test_service(service_id: str, current_user: AdminUser):
    """Test connection to the service using stored config.

    Admin-only: it makes the server issue an outbound request using stored
    admin credentials, so it must not be reachable by every logged-in user.
    """
    if service_id not in store_service_config.SERVICE_META:
        raise HTTPException(status_code=404, detail="Unknown service")
    cfg = await store_service_config.get_config(service_id)
    if not cfg:
        raise HTTPException(status_code=400, detail="No config saved for this service")
    ok, message = await integration_test_service(
        service_id,
        cfg.get("base_url") or "",
        cfg.get("api_key") or "",
    )
    return {"ok": ok, "message": message}


@router.get("/api/service-types")
def api_list_service_types(current_user: CurrentUser):
    """List known service types (id, name, category, default_port, icon, tabs, arr_tables)."""
    return {
        "service_types": [
            {
                "id": st.id,
                "name": st.name,
                "category": st.category,
                "default_port": st.default_port,
                "icon": st.icon,
                "tabs": [asdict(t) for t in st.tabs],
                "arr_tables": st.arr_tables,
            }
            for st in load_extensions().service_types.values()
        ]
    }
