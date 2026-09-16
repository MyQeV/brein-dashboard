"""Emby API client (HTTP and WebSocket for real-time playback events)."""

import asyncio
import json
import logging
import time
from typing import Any, Callable
from urllib.parse import quote, urljoin

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from brein.integrations.api.base import (
    DEFAULT_HTTP_TIMEOUT,
    _is_ssrf_risk_url,
    get_http_client,
    normalize_base_url,
    redirect_message,
)

log = logging.getLogger(__name__)


def _normalize_base_url(base_url: str) -> str | None:
    """normalize_base_url, plus the scheme check; None if invalid."""
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return None
    return base


_CLIENT_IDENTITY = (
    'MediaBrowser Client="Brein", Device="Brein", DeviceId="brein", Version="1"'
)


def _auth_headers(api_key: str) -> dict[str, str]:
    """The API key in both forms Emby and Jellyfin read.

    Emby takes X-Emby-Token. Jellyfin took it too until 12.0, which dropped
    every legacy option (X-Emby-Token, X-Emby-Authorization, ?api_key=) and
    only honours the Authorization header with its MediaBrowser scheme — the
    scheme Emby and every earlier Jellyfin accept as well. The same key goes
    in both headers, so each server reads the one it knows and there is no
    second token to disagree with the first.
    """
    if not api_key:
        return {}
    return {
        "X-Emby-Token": api_key,
        "Authorization": f'MediaBrowser Token="{api_key}"',
    }


# A WebSocket connection that lasted at least this long counts as healthy, so
# the next failure starts from a one-second backoff again.
STABLE_CONNECTION_SECONDS = 60.0

# Message types from Emby WebSocket that indicate playback/session changes.
EMBY_WS_PLAYBACK_MESSAGE_TYPES = frozenset({"UserDataChanged", "Playstate", "Play"})
# Message types that indicate user account changes (trigger users sync).
EMBY_WS_USER_MESSAGE_TYPES = frozenset({"UserUpdated", "UserDeleted"})


async def test_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """Test connection to Emby (GET /System/Info with X-Emby-Token). Returns (success, message)."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, "Invalid base URL"
    url = urljoin(base + "/", "System/Info")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if 300 <= r.status_code < 400:
            return False, redirect_message(r)
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("Connection error to %s: %s", url, e)
        return False, f"Connection failed: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {e!s}"
    except Exception as e:
        log.exception("Request error")
        return False, str(e)


async def get_system_info(base_url: str, api_key: str) -> tuple[bool, dict | None]:
    """GET /System/Info and return JSON. Returns (True, data) on success, (False, None) on error."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, None
    url = urljoin(base + "/", "System/Info")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            return False, None
        return True, r.json()
    except Exception as e:
        log.warning("get_system_info error to %s: %s", url, e)
        return False, None


async def get_system_info_public(
    base_url: str, api_key: str
) -> tuple[bool, dict | None]:
    """GET /System/Info/Public. Returns (True, data) on success, (False, None) on error."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, None
    url = urljoin(base + "/", "System/Info/Public")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            return False, None
        data = r.json()
        return (True, data) if isinstance(data, dict) else (False, None)
    except Exception as e:
        log.warning("get_system_info_public error to %s: %s", url, e)
        return False, None


async def post_system_restart(base_url: str, api_key: str) -> tuple[bool, str]:
    """POST /System/Restart (requires admin API key). Returns (success, message)."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, "Invalid base URL"
    url = urljoin(base + "/", "System/Restart")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().post(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("Connection error to %s: %s", url, e)
        return False, f"Connection failed: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {e!s}"
    except Exception as e:
        log.exception("post_system_restart error")
        return False, str(e)


async def get_users(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """GET /Users/Query; return (True, Items) or (False, None)."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, None
    url = urljoin(base + "/", "Users/Query")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            return False, None
        data = r.json()
        return True, data.get("Items") if isinstance(data, dict) else None
    except Exception as e:
        log.warning("get_users error %s: %s", url, e)
        return False, None


async def authenticate_user(
    base_url: str, username: str, password: str
) -> tuple[bool, dict | None]:
    """POST /Users/AuthenticateByName; return (True, auth_result) or (False, None).
    No API key required — this is the public Emby auth endpoint."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, None
    url = urljoin(base + "/", "Users/AuthenticateByName")
    # The identity in both forms too: Jellyfin 12.0 reads only Authorization.
    headers = {
        "Authorization": _CLIENT_IDENTITY,
        "X-Emby-Authorization": _CLIENT_IDENTITY,
        "Content-Type": "application/json",
    }
    payload = {"Username": username, "Pw": password}
    try:
        r = await get_http_client().post(
            url, headers=headers, json=payload, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            return False, None
        return True, r.json()
    except Exception as e:
        log.warning("authenticate_user error %s: %s", url, e)
        return False, None


async def get_activity_log_entries(
    base_url: str, api_key: str, limit: int = 50, start_index: int = 0
) -> tuple[bool, list]:
    """GET /System/ActivityLog/Entries. Returns (True, items) or (False, []). Items have Id, Name, Overview, Date, UserId, Type, etc."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, []
    url = urljoin(
        base + "/",
        "System/ActivityLog/Entries?Limit={}&StartIndex={}".format(limit, start_index),
    )
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(url, headers=headers, timeout=15.0)
        if r.status_code != 200:
            return False, []
        data = r.json()
        if not isinstance(data, dict):
            return True, []
        items = data.get("Items")
        return True, items if isinstance(items, list) else []
    except Exception as e:
        log.warning("get_activity_log_entries error %s: %s", url, e)
        return False, []


# Max item IDs per batch request (Emby Ids param is comma-delimited)
ITEMS_BATCH_SIZE = 50


async def get_items_by_ids(
    base_url: str, api_key: str, item_ids: list[str]
) -> tuple[bool, list[dict[str, Any]]]:
    """GET /Items?Ids=id1,id2,... (ItemsService getItems). Returns (True, list of item dicts) or (False, []).
    item_ids are sent in one request; pass at most ITEMS_BATCH_SIZE ids per call."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, []
    ids = [str(i or "").strip() for i in item_ids if i is not None and str(i).strip()]
    if not ids:
        return False, []
    url = urljoin(base + "/", "Items")
    headers = _auth_headers(api_key)
    params = {"Ids": ",".join(ids)}
    try:
        r = await get_http_client().get(
            url, headers=headers, params=params, timeout=30.0
        )
        if r.status_code != 200:
            return False, []
        data = r.json()
        if not isinstance(data, dict):
            return False, []
        items = data.get("Items")
        if not items or not isinstance(items, list):
            return True, []
        return True, [i for i in items if isinstance(i, dict)]
    except Exception as e:
        log.warning("get_items_by_ids error %s: %s", url, e)
        return False, []


async def get_item_by_id(
    base_url: str, api_key: str, item_id: str
) -> tuple[bool, dict[str, Any] | None]:
    """GET /Items?Ids={id} (ItemsService getItems). Returns (True, item_dict) with Id, Name, Type, SeriesId, ParentId etc., or (False, None) on error or 404."""
    ok, items = await get_items_by_ids(base_url, api_key, [item_id])
    if not ok or not items:
        return False, None
    return True, items[0]


ITEMS_PAGE_SIZE = 1000
ITEMS_MAX_PAGES = 500


async def get_items_by_type(
    base_url: str, api_key: str, item_type: str
) -> tuple[bool, list[dict[str, Any]]]:
    """GET /Items?Recursive=true&IncludeItemTypes={item_type}, one page at a time.

    Unpaginated, a large library came back as a single response — hundreds of
    megabytes for 50k episodes — which timed out and left that item type
    silently unsynced on every cycle. Pages are requested with StartIndex and
    Limit, and the walk stops on a short page, on the server's own
    TotalRecordCount, or at ITEMS_MAX_PAGES if the server ignores StartIndex.
    """
    base = _normalize_base_url(base_url)
    if not base:
        return False, []
    url = urljoin(base + "/", "Items")
    headers = _auth_headers(api_key)
    collected: list[dict[str, Any]] = []
    start_index = 0
    try:
        client = get_http_client()
        for _ in range(ITEMS_MAX_PAGES):
            params = {
                "Recursive": "true",
                "IncludeItemTypes": item_type,
                "StartIndex": str(start_index),
                "Limit": str(ITEMS_PAGE_SIZE),
            }
            r = await client.get(url, headers=headers, params=params, timeout=60.0)
            if r.status_code != 200:
                return False, []
            data = r.json()
            if not isinstance(data, dict):
                return False, []
            items = data.get("Items")
            if not items or not isinstance(items, list):
                break
            collected.extend(i for i in items if isinstance(i, dict))
            if len(items) < ITEMS_PAGE_SIZE:
                break
            total = data.get("TotalRecordCount")
            if isinstance(total, int) and len(collected) >= total:
                break
            start_index += ITEMS_PAGE_SIZE
        else:
            log.warning(
                "get_items_by_type(%s): stopped after %d pages",
                item_type,
                ITEMS_MAX_PAGES,
            )
        return True, collected
    except Exception as e:
        log.warning("get_items_by_type(%s) error %s: %s", item_type, url, e)
        return False, []


async def get_sessions(
    base_url: str, api_key: str, active_within_seconds: int | None = 30
) -> list | None:
    """GET /Sessions; the active session objects, or None on failure.

    `[]` means the server answered and nothing is playing; None means it did
    not answer, and the caller has to leave the instance alone for that tick
    rather than show it idle (the same split plex.get_sessions makes).
    When active_within_seconds is set, only sessions active within that many
    seconds are returned (smaller payload).
    """
    base = _normalize_base_url(base_url)
    if not base:
        return None
    url = urljoin(base + "/", "Sessions")
    headers = _auth_headers(api_key)
    params = (
        {"ActiveWithinSeconds": active_within_seconds}
        if active_within_seconds is not None
        else {}
    )
    try:
        r = await get_http_client().get(
            url, headers=headers, params=params, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            log.warning("get_sessions HTTP %s from %s", r.status_code, base)
            return None
        data = r.json()
        return data if isinstance(data, list) else None
    except Exception as e:
        log.warning("get_sessions error %s: %s", url, e)
        return None


def emby_websocket_url(base_url: str, api_key: str, device_id: str = "brein") -> str:
    """Build Emby WebSocket URL from HTTP base_url. Replaces http->ws, https->wss and adds api_key and deviceId."""
    base = _normalize_base_url(base_url)
    if not base:
        return ""
    if base.startswith("https://"):
        host_part = base[len("https://") :]
        scheme = "wss"
    elif base.startswith("http://"):
        host_part = base[len("http://") :]
        scheme = "ws"
    else:
        return ""
    # Percent-encode both values: an API key containing &, # or + would
    # otherwise split the query string and break the connection.
    key = quote(api_key or "", safe="")
    device = quote(device_id or "", safe="")
    return f"{scheme}://{host_part}?api_key={key}&deviceId={device}"


async def _invoke_callback(callback: Callable[..., Any], label: str) -> None:
    """Invoke a sync or async callback, logging any errors."""
    try:
        if asyncio.iscoroutinefunction(callback):
            await callback()
        else:
            callback()
    except Exception as e:
        log.warning("Emby WebSocket %s error: %s", label, e)


def _decode_ws_raw(raw: bytes | str) -> str:
    """Decode raw WebSocket frame to str."""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw or ""


async def _process_ws_message(
    raw_str: str,
    instance_id: int | None,
    on_playback_event: Callable[..., Any],
    on_user_event: Callable[..., Any] | None,
) -> None:
    """Parse a raw WebSocket message and fire the appropriate callbacks."""
    try:
        msg = json.loads(raw_str) if raw_str else None
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.debug(
            "Emby WebSocket frame was not JSON (instance_id=%s): %s", instance_id, e
        )
        await _invoke_callback(on_playback_event, "on_playback_event")
        return

    if not isinstance(msg, dict):
        await _invoke_callback(on_playback_event, "on_playback_event")
        return

    message_type = msg.get("MessageType") or msg.get("messageType")

    if message_type in EMBY_WS_PLAYBACK_MESSAGE_TYPES:
        log.debug(
            "Emby WebSocket playback event: %s (instance_id=%s)",
            message_type,
            instance_id or "",
        )
        await _invoke_callback(on_playback_event, "on_playback_event")

    if message_type in EMBY_WS_USER_MESSAGE_TYPES and on_user_event:
        log.debug(
            "Emby WebSocket user event: %s (instance_id=%s)",
            message_type,
            instance_id or "",
        )
        await _invoke_callback(on_user_event, "on_user_event")


async def run_emby_websocket_listener(
    base_url: str,
    api_key: str,
    on_playback_event: Callable[..., Any],
    *,
    device_id: str = "brein",
    instance_id: int | None = None,
    on_user_event: Callable[..., Any] | None = None,
) -> None:
    """Connect to Emby WebSocket and dispatch events to callbacks.

    Calls on_playback_event() on playback-related messages and on_user_event()
    on user change messages. Reconnects with exponential backoff until cancelled.
    """
    url = emby_websocket_url(base_url, api_key, device_id)
    if not url:
        log.warning("Emby WebSocket: invalid base_url %s", base_url)
        return
    # websockets.connect does not go through the httpx client, so the SSRF
    # hook attached there never sees this connection.
    if await _is_ssrf_risk_url(base_url):
        log.warning("Emby WebSocket: blocked base_url %s", base_url)
        return
    backoff = 1.0
    max_backoff = 60.0
    connected_at = 0.0
    while True:
        try:
            async with websockets.connect(
                url, ping_interval=30, ping_timeout=10, close_timeout=5
            ) as ws:
                connected_at = time.monotonic()
                log.info("Emby WebSocket connected to %s", base_url)
                while True:
                    raw = await ws.recv()
                    await _process_ws_message(
                        _decode_ws_raw(raw),
                        instance_id,
                        on_playback_event,
                        on_user_event,
                    )
        except ConnectionClosed as e:
            log.debug("Emby WebSocket closed %s: %s", base_url, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Emby WebSocket error %s: %s", base_url, e)

        # Reset only after the connection proved itself. Resetting on connect
        # meant a server that accepted the upgrade and dropped the socket at
        # once reconnected every second forever. Same logic as the Plex
        # listener, which explains why it sits on the failure path.
        if (
            connected_at
            and time.monotonic() - connected_at >= STABLE_CONNECTION_SECONDS
        ):
            backoff = 1.0
        connected_at = 0.0
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            raise
        backoff = min(backoff * 2, max_backoff)


async def _get_library_media_folders(base_url: str, api_key: str) -> list:
    """GET /Library/MediaFolders; return list of items with Id, Name, ServerId, Guid, Type, CollectionType."""
    base = _normalize_base_url(base_url)
    if not base:
        return []
    url = urljoin(base + "/", "Library/MediaFolders")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            return []
        data = r.json()
        items = data.get("Items") if isinstance(data, dict) else []
        out = []
        for it in items or []:
            if isinstance(it, dict) and it.get("Id") is not None:
                out.append(
                    {
                        "Id": it["Id"],
                        "Name": it.get("Name") or str(it["Id"]),
                        "ServerId": it.get("ServerId"),
                        "Guid": it.get("Guid"),
                        "Type": it.get("Type"),
                        "CollectionType": it.get("CollectionType"),
                    }
                )
        return out
    except Exception as e:
        log.warning("_get_library_media_folders error %s: %s", url, e)
        return []


async def get_media_folders(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """Return (True, merged list) of all folder/library IDs valid for user policy EnabledFolders.
    Merges Library/MediaFolders (library view GUIDs) and Library/SelectableMediaFolders (folders + subfolders)
    so both ID types appear (e.g. da4b4c8383874c81b33463aed6c92c9f from MediaFolders). Dedupes by Id."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, None
    headers = _auth_headers(api_key)
    seen = set()
    out = []

    # 1) Library/MediaFolders (library views - IDs like da4b4c8383874c81b33463aed6c92c9f)
    try:
        media_folder_items = await _get_library_media_folders(base_url, api_key)
        for it in media_folder_items:
            sid = str(it["Id"])
            if sid not in seen:
                seen.add(sid)
                out.append(it)
    except Exception:
        # First of two strategies; SelectableMediaFolders below is the
        # fallback, so a failure here is not terminal.
        log.debug("Emby VirtualFolders lookup failed", exc_info=True)

    # 2) Library/SelectableMediaFolders (folders + subfolders)
    url = urljoin(base + "/", "Library/SelectableMediaFolders")
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            return (True, out) if out else (False, None)
        data = r.json()
        if isinstance(data, list):
            folders = data
        elif isinstance(data, dict) and "Items" in data:
            folders = data["Items"]
        else:
            folders = []
        for folder in folders:
            if not isinstance(folder, dict) or folder.get("Id") is None:
                continue
            parent_name = folder.get("Name") or str(folder["Id"])
            sid = str(folder["Id"])
            if sid not in seen:
                seen.add(sid)
                out.append(
                    {
                        "Id": folder["Id"],
                        "Name": parent_name,
                        "Guid": folder.get("Guid"),
                    }
                )
            for sub in folder.get("SubFolders") or []:
                if not isinstance(sub, dict) or sub.get("Id") is None:
                    continue
                sub_sid = str(sub["Id"])
                if sub_sid not in seen:
                    seen.add(sub_sid)
                    sub_name = sub.get("Name") or str(sub["Id"])
                    out.append(
                        {
                            "Id": sub["Id"],
                            "Name": f"{parent_name} - {sub_name}",
                            "Guid": sub.get("Guid"),
                        }
                    )
    except Exception as e:
        log.warning("get_media_folders SelectableMediaFolders error %s: %s", url, e)
        if not out:
            return False, None

    return True, out


async def get_user_by_id(
    base_url: str, api_key: str, user_id: str
) -> tuple[bool, dict | None]:
    """GET /Users/{Id}; (True, user_dto) on 200, (True, None) when the server
    answered 404, (False, None) when it did not answer."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, None
    url = urljoin(base + "/", f"Users/{user_id}")
    headers = _auth_headers(api_key)
    try:
        r = await get_http_client().get(
            url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code == 404:
            return True, None
        if r.status_code != 200:
            return False, None
        return True, r.json()
    except Exception as e:
        log.warning("get_user_by_id error %s: %s", url, e)
        return False, None


async def update_user_policy(
    base_url: str,
    api_key: str,
    user_id: str,
    enable_all_folders: bool | None = None,
    enabled_folder_ids: list[str] | None = None,
    is_disabled: bool | None = None,
    is_administrator: bool | None = None,
    enable_live_tv: bool | None = None,
    enable_live_tv_management: bool | None = None,
    max_simultaneous_streams: int | None = None,
    is_hidden: bool | None = None,
    is_hidden_remotely: bool | None = None,
    is_hidden_from_unused_devices: bool | None = None,
    remote_client_bitrate_limit: int | None = None,
    auto_remote_quality: int | None = None,
) -> tuple[bool, str]:
    """Update user policy. GET user then POST /Users/{Id}/Policy with updated Policy. Returns (True, 'OK') or (False, error_message)."""
    ok, user = await get_user_by_id(base_url, api_key, user_id)
    if not ok or not user:
        return False, "User not found"
    policy = user.get("Policy") or {}
    if not isinstance(policy, dict):
        policy = {}
    if enable_all_folders is not None:
        policy["EnableAllFolders"] = enable_all_folders
    if enabled_folder_ids is not None:
        # Resolve folder IDs to GUIDs; Emby Policy.EnabledFolders expects GUIDs, not numeric IDs.
        ok_folders, raw_folders = await get_media_folders(base_url, api_key)
        id_to_guid = {}
        if ok_folders and raw_folders:
            for it in raw_folders:
                if isinstance(it, dict) and it.get("Id") is not None:
                    sid = str(it["Id"])
                    g = it.get("Guid")
                    id_to_guid[sid] = g.strip() if g and str(g).strip() else sid
        policy["EnabledFolders"] = [
            id_to_guid.get(str(fid).strip(), str(fid).strip())
            for fid in enabled_folder_ids
        ]
    if is_disabled is not None:
        policy["IsDisabled"] = is_disabled
    if is_administrator is not None:
        policy["IsAdministrator"] = is_administrator
    if enable_live_tv is not None:
        policy["EnableLiveTvAccess"] = enable_live_tv
    if enable_live_tv_management is not None:
        policy["EnableLiveTvManagement"] = enable_live_tv_management
    if max_simultaneous_streams is not None:
        policy["SimultaneousStreamLimit"] = max_simultaneous_streams
    if is_hidden is not None:
        policy["IsHidden"] = is_hidden
    if is_hidden_remotely is not None:
        policy["IsHiddenRemotely"] = is_hidden_remotely
    if is_hidden_from_unused_devices is not None:
        policy["IsHiddenFromUnusedDevices"] = is_hidden_from_unused_devices
    if remote_client_bitrate_limit is not None:
        policy["RemoteClientBitrateLimit"] = remote_client_bitrate_limit
    if auto_remote_quality is not None:
        policy["AutoRemoteQuality"] = auto_remote_quality
    base = _normalize_base_url(base_url)
    if not base:
        return False, "Invalid base URL"
    url = urljoin(base + "/", f"Users/{user_id}/Policy")
    headers = {**_auth_headers(api_key), "Content-Type": "application/json"}
    try:
        r = await get_http_client().post(
            url, headers=headers, json=policy, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code >= 400:
            log.warning(
                "update_user_policy HTTP %s url=%s body=%s",
                r.status_code,
                url,
                r.text[:500],
            )
            return False, f"HTTP {r.status_code}"
        log.debug("update_user_policy %s status %s", url, r.status_code)
        return True, "OK"
    except Exception as e:
        log.warning("update_user_policy error %s: %s", url, e)
        return False, str(e)


async def update_user(
    base_url: str, api_key: str, user_id: str, name: str
) -> tuple[bool, str]:
    """Update user display name. GET current user DTO then POST /Users/{Id} with updated Name."""
    ok, user = await get_user_by_id(base_url, api_key, user_id)
    if not ok or not user:
        return False, "User not found"
    user["Name"] = name
    user.pop("Policy", None)
    user.pop("Configuration", None)
    base = _normalize_base_url(base_url)
    if not base:
        return False, "Invalid base URL"
    url = urljoin(base + "/", f"Users/{user_id}")
    headers = {**_auth_headers(api_key), "Content-Type": "application/json"}
    try:
        r = await get_http_client().post(
            url, headers=headers, json=user, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except Exception as e:
        log.warning("update_user error %s: %s", url, e)
        return False, str(e)


async def update_user_password(
    base_url: str, api_key: str, user_id: str, new_password: str
) -> tuple[bool, str]:
    """Set a new password for a user via POST /Users/{Id}/Password."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, "Invalid base URL"
    url = urljoin(base + "/", f"Users/{user_id}/Password")
    headers = {**_auth_headers(api_key), "Content-Type": "application/json"}
    payload = {"NewPw": new_password}
    try:
        r = await get_http_client().post(
            url, headers=headers, json=payload, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code >= 400:
            detail = r.text[:300].strip() if r.text else ""
            return False, detail or f"HTTP {r.status_code}"
        return True, "OK"
    except Exception as e:
        log.warning("update_user_password error %s: %s", url, e)
        return False, str(e)
