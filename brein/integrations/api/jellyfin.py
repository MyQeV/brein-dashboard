"""Jellyfin API client — mostly identical to Emby; overrides where the API differs."""

import logging

from brein.integrations.api.emby import (
    _auth_headers,
    _get_library_media_folders,
    get_user_by_id,
    get_activity_log_entries,
    authenticate_user,
    update_user,
    update_user_password,
    update_user_policy,
    get_sessions,
    get_items_by_type,
    get_system_info_public,
    post_system_restart,
)

__all__ = [
    "get_users",
    "get_media_folders",
    "get_user_by_id",
    "get_activity_log_entries",
    "authenticate_user",
    "update_user",
    "update_user_password",
    "update_user_policy",
    "get_sessions",
    "get_items_by_type",
    "test_connection",
    "get_system_info_public",
    "post_system_restart",
]

log = logging.getLogger(__name__)


async def get_media_folders(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """GET /Library/MediaFolders only — Jellyfin lacks SelectableMediaFolders."""
    items = await _get_library_media_folders(base_url, api_key)
    return (True, items) if items else (False, None)


async def get_users(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """GET /Users — Jellyfin returns a plain list, unlike Emby's Users/Query wrapper."""
    from brein.integrations.api.base import get_http_client, DEFAULT_HTTP_TIMEOUT
    from urllib.parse import urljoin

    base = (base_url or "").strip().rstrip("/")
    if not base:
        return False, None
    url = urljoin(base + "/", "Users")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            return False, None
        data = r.json()
        if isinstance(data, list):
            return True, data
        if isinstance(data, dict) and "Items" in data:
            return True, data["Items"]
        return False, None
    except Exception as e:
        log.warning("get_users error %s: %s", url, e)
        return False, None


async def test_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """Test connection to Jellyfin (GET /System/Info with the API key). Returns (success, message)."""
    from brein.integrations.api.base import get_http_client, DEFAULT_HTTP_TIMEOUT
    from urllib.parse import urljoin

    base = (base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return False, "Invalid base URL"
    url = urljoin(base + "/", "System/Info")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except Exception as e:
        return False, str(e)
