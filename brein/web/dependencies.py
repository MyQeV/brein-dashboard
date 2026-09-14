"""Shared FastAPI dependencies for routers."""

from fastapi import HTTPException

from brein.store import instances as store_instances


async def require_instance_config(instance_id: int) -> tuple[str, str, str]:
    """Return (service_type, base_url, api_key) or raise HTTPException 404/400.

    Use this in routers that need to validate and fetch instance connection
    details before making an external API call.
    """
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Instance not found")
    service_type, base_url, api_key = cfg
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="Configure host and API key first")
    return service_type, base_url, api_key
