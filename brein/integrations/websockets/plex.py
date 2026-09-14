"""Plex Media Server notification WebSocket — outbound client, append events to DB."""

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosed

from brein.store import plex_ws_events as store_plex_ws_events

log = logging.getLogger(__name__)

# A connection that lasted at least this long counts as healthy, so the next
# failure starts from a one-second backoff again.
STABLE_CONNECTION_SECONDS = 60.0


def _normalize_base_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return ""
    return base


def plex_notification_websocket_url(base_url: str, api_key: str) -> str:
    """Build PMS notifications WebSocket URL (ws/wss + /:/websockets/notifications + token)."""
    base = _normalize_base_url(base_url)
    if not base or not api_key:
        return ""
    if base.startswith("https://"):
        host_part = base[len("https://") :]
        scheme = "wss"
    else:
        host_part = base[len("http://") :]
        scheme = "ws"
    tok = quote(api_key, safe="")
    return f"{scheme}://{host_part}/:/websockets/notifications?X-Plex-Token={tok}"


def _guess_event_type(raw_str: str) -> str | None:
    if not raw_str or not raw_str.lstrip().startswith("{"):
        return None
    try:
        msg = json.loads(raw_str)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None
    for key in ("type", "Type", "notificationType", "Notification"):
        v = msg.get(key)
        if v is not None and isinstance(v, str):
            return v[:128]
        if v is not None and not isinstance(v, (dict, list)):
            return str(v)[:128]
    return None


async def _invoke_store(instance_id: int, raw_str: str) -> None:
    event_type = _guess_event_type(raw_str)
    await store_plex_ws_events.append_event(instance_id, raw_str, event_type=event_type)


async def run_plex_notification_listener(
    base_url: str,
    api_key: str,
    instance_id: int,
) -> None:
    """Connect to PMS notifications WebSocket; persist each frame; reconnect with backoff."""
    url = plex_notification_websocket_url(base_url, api_key)
    if not url:
        log.warning(
            "Plex WebSocket: invalid base_url or token (instance_id=%s)", instance_id
        )
        return
    backoff = 1.0
    max_backoff = 60.0
    connected_at = 0.0
    extra_headers = {
        "X-Plex-Client-Identifier": "brein-media-dashboard",
        "X-Plex-Product": "Brein",
        "X-Plex-Version": "1.0",
    }
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5,
                additional_headers=extra_headers,
            ) as ws:
                connected_at = time.monotonic()
                log.info(
                    "Plex WebSocket connected instance_id=%s url_host=%s",
                    instance_id,
                    base_url[:48] if base_url else "",
                )
                while True:
                    raw: Any = await ws.recv()
                    raw_str = (
                        raw.decode("utf-8", errors="replace")
                        if isinstance(raw, (bytes, bytearray))
                        else (raw or "")
                    )
                    await _invoke_store(instance_id, raw_str)
        except ConnectionClosed as e:
            log.debug("Plex WebSocket closed instance_id=%s: %s", instance_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Plex WebSocket error instance_id=%s: %s", instance_id, e)

        # Reset only after the connection proved itself. Resetting on connect
        # meant a failure that recurs *after* connecting — a write error on
        # every frame, say — reconnected once a second forever.
        #
        # This has to sit on the failure path, not after the `async with`: the
        # receive loop above can only leave by raising, so a reset placed there
        # never ran at all, and six drops over a container's lifetime left
        # every later reconnect waiting the full minute however long the
        # connection before it had lasted.
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
