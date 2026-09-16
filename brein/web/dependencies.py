"""Shared FastAPI dependencies for routers."""

from fastapi import HTTPException

from brein.store import instances as store_instances


async def require_instance_config(
    instance_id: int,
    service_type: str | tuple[str, ...] | None = None,
    *,
    detail: str | None = None,
    status_code: int = 400,
) -> tuple[str, str, str]:
    """Return (service_type, base_url, api_key) or raise HTTPException 404/400.

    Use this in routers that need to validate and fetch instance connection
    details before making an external API call. With `service_type` the
    instance must also be one of those kinds; a mismatch fails with
    `status_code` and `detail`, which a route sets to whatever it has always
    answered.
    """
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Instance not found")
    actual, base_url, api_key = cfg
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="Configure host and API key first")
    if service_type is not None:
        allowed = (service_type,) if isinstance(service_type, str) else service_type
        if actual not in allowed:
            raise HTTPException(
                status_code=status_code,
                detail=detail or f"Not a {' or '.join(allowed)} instance",
            )
    return actual, base_url, api_key
