"""Plex API client."""

import json
import logging
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin

import httpx

from brein.integrations.api.base import (
    DEFAULT_HTTP_TIMEOUT,
    new_http_client,
    normalize_base_url,
    redirect_message,
)

log = logging.getLogger(__name__)

_PLEX_HEADERS_BASE = {"Accept": "application/json"}

_LOG_BODY_SNIP_LEN = 300


def _media_container_items(container: dict[str, Any], key: str) -> list:
    """Return MediaContainer[key] as a list. Plex may return one item as a dict instead of a one-element list."""
    raw = container.get(key)
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    return []


def _session_history_items(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect history rows from MediaContainer JSON (Video/Track/Metadata; Hub nesting; alternate casing)."""
    items: list[dict[str, Any]] = []
    for key in (
        "Video",
        "Track",
        "Metadata",
        "video",
        "track",
        "metadata",
    ):
        items.extend(_media_container_items(container, key))
    if items:
        return items
    hubs = container.get("Hub") or container.get("hub")
    hub_list: list[Any]
    if isinstance(hubs, list):
        hub_list = hubs
    elif isinstance(hubs, dict):
        hub_list = [hubs]
    else:
        hub_list = []
    for hub in hub_list:
        if not isinstance(hub, dict):
            continue
        for key in (
            "Video",
            "Track",
            "Metadata",
            "video",
            "track",
            "metadata",
        ):
            items.extend(_media_container_items(hub, key))
    if items:
        return items
    for v in container.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            sample = v[0]
            if any(
                k in sample for k in ("viewedAt", "viewed_at", "accountID", "ratingKey")
            ):
                items.extend([x for x in v if isinstance(x, dict)])
                break
    return items


def _history_items_from_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse session history when PMS returns XML (often ignores Accept: application/json)."""
    out: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag in ("Video", "Track", "Metadata") and el.attrib:
            out.append(dict(el.attrib))
    return out


def _media_container_total_size(container: dict[str, Any]) -> int | None:
    """Best-effort count from MediaContainer (Plex uses totalSize; size may match on some responses)."""
    for key in ("totalSize", "total_size", "size"):
        v = container.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def _xml_media_container_size(xml_text: str) -> int | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag != "MediaContainer":
        return None
    s = root.attrib.get("size")
    if s is not None:
        try:
            return int(s)
        except ValueError:
            pass
    return None


def _parse_history_response_body(body: str) -> tuple[list[dict[str, Any]], int | None]:
    """Parse JSON or XML body from /status/sessions/history/all. Returns (items, totalSize from container)."""
    text = body or ""
    stripped = text.lstrip("\ufeff").strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        else:
            if isinstance(data, dict):
                container = data.get("MediaContainer")
                if isinstance(container, dict):
                    ts = _media_container_total_size(container)
                    items = _session_history_items(container)
                    return items, ts
            return [], None
    if "<MediaContainer" in text or stripped.startswith("<?xml"):
        items = _history_items_from_xml(text)
        ts = _xml_media_container_size(text)
        return items, ts
    return [], None


def _normalize_base_url(base_url: str) -> str | None:
    """normalize_base_url, plus the scheme check; None if invalid."""
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return None
    return base


async def test_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """Test connection to Plex (GET /library/sections with X-Plex-Token). Returns (success, message).

    /identity is served without a token, so probing it passed any token at
    all; /library/sections is refused without a valid one.
    """
    base = _normalize_base_url(base_url)
    if not base:
        return False, "Invalid base URL"
    url = urljoin(base + "/", "library/sections")
    headers = (
        {**_PLEX_HEADERS_BASE, "X-Plex-Token": api_key}
        if api_key
        else _PLEX_HEADERS_BASE
    )
    try:
        async with new_http_client(DEFAULT_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            if 300 <= r.status_code < 400:
                return False, redirect_message(r)
            if r.status_code == 401:
                return False, "Invalid token"
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


async def get_identity(base_url: str, api_key: str) -> tuple[bool, dict | None]:
    """GET /identity and return server info. Returns (True, data) on success, (False, None) on error.
    data keys: machineIdentifier, version, platform."""
    base = _normalize_base_url(base_url)
    if not base:
        return False, None
    url = urljoin(base + "/", "identity")
    headers = (
        {**_PLEX_HEADERS_BASE, "X-Plex-Token": api_key}
        if api_key
        else _PLEX_HEADERS_BASE
    )
    try:
        async with new_http_client(DEFAULT_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return False, None
            data = r.json()
            container = data.get("MediaContainer") if isinstance(data, dict) else None
            if not isinstance(container, dict):
                return False, None
            return True, {
                "machineIdentifier": container.get("machineIdentifier") or "",
                "version": container.get("version") or "",
                "platform": container.get("platform") or "",
            }
    except Exception as e:
        log.warning("get_identity error %s: %s", url, e)
        return False, None


_PLEX_TV_BASE = "https://plex.tv"
_PLEX_TV_HEADERS = {
    **_PLEX_HEADERS_BASE,
    "X-Plex-Client-Identifier": "brein-media-dashboard",
    "X-Plex-Product": "Brein",
    "X-Plex-Version": "1.0",
}


async def get_users(base_url: str, api_key: str) -> list:
    """GET https://plex.tv/api/v2/home/users; return list of home user dicts. Empty list on error.
    base_url is ignored — always calls plex.tv.
    Each dict contains: id, uuid, title, username, email, thumb, home, restricted, admin."""
    if not api_key:
        return []
    url = f"{_PLEX_TV_BASE}/api/v2/home/users"
    headers = {**_PLEX_TV_HEADERS, "X-Plex-Token": api_key}
    try:
        async with new_http_client(DEFAULT_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                log.warning(
                    "get_users plex.tv returned HTTP %s: %s",
                    r.status_code,
                    r.text[:200],
                )
                return []
            data = r.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("users", "Users", "MediaContainer"):
                    val = data.get(key)
                    if isinstance(val, list):
                        return val
            return []
    except Exception as e:
        log.warning("get_users plex.tv error: %s", e)
        return []


async def get_libraries(base_url: str, api_key: str) -> list:
    """GET /library/sections/all; return list of library section dicts. Empty list on error.
    Each dict contains: key, title, type, agent, scanner, language, uuid, updatedAt, createdAt."""
    base = _normalize_base_url(base_url)
    if not base:
        return []
    url = urljoin(base + "/", "library/sections/all")
    headers = (
        {**_PLEX_HEADERS_BASE, "X-Plex-Token": api_key}
        if api_key
        else _PLEX_HEADERS_BASE
    )
    try:
        async with new_http_client(DEFAULT_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                log.warning(
                    "get_libraries HTTP %s %s: %s",
                    r.status_code,
                    url,
                    r.text[:_LOG_BODY_SNIP_LEN],
                )
                return []
            data = r.json()
            container = data.get("MediaContainer") if isinstance(data, dict) else None
            if not isinstance(container, dict):
                return []
            return _media_container_items(container, "Directory")
    except Exception as e:
        log.warning("get_libraries error %s: %s", url, e)
        return []


async def get_sessions(base_url: str, api_key: str) -> list | None:
    """GET /status/sessions; the active session Metadata dicts, or None on failure.

    The two outcomes must stay distinct. `[]` means the server answered and
    nothing is playing, which finalises the sessions it no longer lists; None
    means it did not answer, and the caller has to leave the live rows alone.
    Returning `[]` for both meant one slow poll — a library scan, a restart,
    the 10s timeout — ended every stream and started a fresh one 10 seconds
    later, turning three people watching into six plays.

    Each session dict contains: ratingKey, title, type, grandparentTitle,
    duration, viewOffset, User (dict with id/title), Player (dict with
    state/device/title), Session (dict with id).
    """
    base = _normalize_base_url(base_url)
    if not base:
        return None
    url = urljoin(base + "/", "status/sessions")
    headers = (
        {**_PLEX_HEADERS_BASE, "X-Plex-Token": api_key}
        if api_key
        else _PLEX_HEADERS_BASE
    )
    try:
        async with new_http_client(DEFAULT_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                log.warning(
                    "get_sessions HTTP %s %s: %s",
                    r.status_code,
                    url,
                    r.text[:_LOG_BODY_SNIP_LEN],
                )
                return None
            data = r.json()
            container = data.get("MediaContainer") if isinstance(data, dict) else None
            if not isinstance(container, dict):
                return None
            return _status_sessions_items(container)
    except Exception as e:
        log.warning("get_sessions error %s: %s", url, e)
        return None


def _status_sessions_items(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Active sessions may appear as Metadata, Video, or Track depending on PMS version."""
    out: list[dict[str, Any]] = []
    for key in (
        "Metadata",
        "Video",
        "Track",
        "metadata",
        "video",
        "track",
    ):
        out.extend(_media_container_items(container, key))
    return out


def parse_rating_key_from_library_key(key: str | None) -> str | None:
    """Derive rating key string from a Plex ``key`` path (e.g. ``/library/metadata/12345``)."""
    if not key or not isinstance(key, str):
        return None
    s = key.strip()
    if not s:
        return None
    if "/library/metadata/" in s:
        tail = s.split("/library/metadata/", 1)[-1].strip("/").split("/")[0]
        return tail[:128] if tail else None
    if s.isdigit():
        return s[:128]
    return None


def rating_key_from_plex_metadata_dict(m: dict[str, Any]) -> str | None:
    """Stable item id for Plex metadata (library or session-shaped)."""
    rk = m.get("ratingKey")
    if rk is not None and str(rk).strip():
        return str(rk).strip()[:128]
    return parse_rating_key_from_library_key(m.get("key"))


def rating_key_from_plex_session_dict(s: dict[str, Any]) -> str | None:
    """Rating key from a live session dict (same fields as metadata; tighter length for DB column)."""
    rk = s.get("ratingKey")
    if rk is not None and str(rk).strip():
        return str(rk).strip()[:64]
    return parse_rating_key_from_library_key(s.get("key"))


# Plex PMS media filter types for GET /library/all?type= (see Plex API metadata types).
PLEX_LIBRARY_MEDIA_TYPES: tuple[int, ...] = (1, 2, 3, 4)


async def get_library_all_items_page(
    base_url: str,
    api_key: str,
    media_type: int,
    start: int,
    page_size: int,
) -> tuple[list[dict[str, Any]] | None, int | None]:
    """GET /library/all with type filter and container pagination headers.

    Returns (Metadata dicts, totalSize or None), or (None, None) when the
    request failed. The caller walks pages until one comes back empty, so a
    failure returned as `[]` was indistinguishable from the end of the
    library: the sync stopped early, counted itself complete, and stamped
    `last_scan_date` over a partial pass.
    """
    base = _normalize_base_url(base_url)
    if not base:
        return None, None
    if page_size < 1:
        page_size = 1
    if start < 0:
        start = 0
    url = urljoin(base + "/", "library/all")
    headers = {
        **_PLEX_HEADERS_BASE,
        "X-Plex-Container-Start": str(start),
        "X-Plex-Container-Size": str(page_size),
    }
    if api_key:
        headers["X-Plex-Token"] = api_key
    try:
        async with new_http_client(DEFAULT_HTTP_TIMEOUT) as client:
            r = await client.get(
                url,
                headers=headers,
                params={"type": str(media_type)},
            )
            if r.status_code != 200:
                log.warning(
                    "get_library_all_items_page HTTP %s %s: %s",
                    r.status_code,
                    url,
                    r.text[:_LOG_BODY_SNIP_LEN],
                )
                return None, None
            data = r.json()
            container = data.get("MediaContainer") if isinstance(data, dict) else None
            if not isinstance(container, dict):
                return None, None
            total = _media_container_total_size(container)
            items = _session_history_items(container)
            return items, total
    except Exception as e:
        log.warning("get_library_all_items_page error %s: %s", url, e)
        return None, None
