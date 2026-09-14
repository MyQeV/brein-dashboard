"""Now-playing API (aggregate Emby sessions) and WebSocket for live updates."""

import asyncio
import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from brein import cache as brein_cache
from brein import config as brein_config
from brein.integrations import emby as emby_integration
from brein.integrations import plex as plex_integration
from brein.integrations.api.plex import rating_key_from_plex_session_dict
from brein.web import auth as web_auth
from brein.web import on_login_tasks as web_on_login_tasks
from brein.web.schemas import User
from brein.store import instances as store_instances
from brein.store import plex_dashboard_metrics as store_plex_dashboard_metrics
from brein.store import plex_playback_sessions as store_plex_playback

log = logging.getLogger(__name__)

# A client that cannot take an update within this long is treated as gone.
BROADCAST_SEND_TIMEOUT = 5.0

_last_plex_snapshot_rebuild: float = 0.0
router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]

NOW_PLAYING_CACHE_KEY = "now_playing:state"

# Connection manager for /ws/now-playing: set of active WebSocket connections.
_ws_connections: set[WebSocket] = set()

WS_UNAUTHORIZED_CLOSE_CODE = 4001
WS_MAX_CONNECTIONS = 100


async def broadcast_now_playing(payload: dict) -> None:
    """Send payload as JSON to all connected WebSocket clients; remove dead connections."""
    text = json.dumps(payload)
    targets = list(_ws_connections)
    # Concurrently, and with a deadline: sending in sequence let one
    # half-open client block every other client's update until the socket
    # timed out, which also stalled the broadcast task itself.
    results = await asyncio.gather(
        *(
            asyncio.wait_for(ws.send_text(text), BROADCAST_SEND_TIMEOUT)
            for ws in targets
        ),
        return_exceptions=True,
    )
    for ws, result in zip(targets, results):
        if isinstance(result, BaseException):
            _ws_connections.discard(ws)
    n = len(_ws_connections)
    if n > 0:
        log.debug("broadcast_now_playing: sent to %d client(s)", n)


def _normalize_session(
    s: dict,
    instance_id: int,
    instance_label: str,
    app_url: str,
    server_id: str,
) -> dict | None:
    """Convert an Emby session dict to a normalized now-playing item. Returns None if nothing is playing."""
    now = s.get("NowPlayingItem")
    if not now or not isinstance(now, dict):
        return None
    play = s.get("PlayState") or {}
    if not isinstance(play, dict):
        play = {}
    item_id = now.get("Id")
    image_tags = now.get("ImageTags") or {}
    image_tag = image_tags.get("Primary") or "" if isinstance(image_tags, dict) else ""
    play_method_raw = play.get("PlayMethod")
    play_method = (
        play_method_raw.strip()
        if isinstance(play_method_raw, str)
        else (play_method_raw or "")
    )
    item_id_str = str(item_id) if item_id is not None else ""
    _base = (app_url or "").rstrip("/")
    item_url = (
        f"{_base}/web/index.html#!/item?id={item_id_str}&serverId={server_id}"
        if _base and server_id and item_id_str
        else ""
    )
    return {
        "session_id": f"{instance_id}:{s.get('Id') or ''}",
        "instance_id": instance_id,
        "instance_label": instance_label,
        "service_type": "emby",
        "app_url": app_url,
        "server_id": server_id,
        "item_url": item_url,
        "user_id": str(s.get("UserId") or ""),
        "user_name": (s.get("UserName") or "").strip(),
        "device_name": (s.get("DeviceName") or "").strip(),
        "item": {
            "id": str(item_id) if item_id is not None else "",
            "name": now.get("Name") or str(item_id or ""),
            "type": now.get("Type") or "Unknown",
            "run_time_ticks": now.get("RunTimeTicks") or 0,
            "image_tag": image_tag,
            "series_name": now.get("SeriesName") or "",
            "series_id": str(now["SeriesId"])
            if now.get("SeriesId") is not None
            else None,
            "index_number": now.get("IndexNumber"),
            "parent_index_number": now.get("ParentIndexNumber"),
        },
        "position_ticks": play.get("PositionTicks") or 0,
        "is_paused": bool(play.get("IsPaused")),
        "play_method": play_method,
    }


# Plex uses milliseconds; Emby uses 100-nanosecond ticks. Conversion: ms × 10000 = ticks.
_PLEX_MS_TO_TICKS = 10000
# Plex type names are lowercase; normalize to title-case to match Emby.
_PLEX_TYPE_MAP = {
    "movie": "Movie",
    "episode": "Episode",
    "track": "Track",
    "clip": "Clip",
}


def _normalize_plex_session(
    s: dict,
    instance_id: int,
    instance_label: str,
    app_url: str,
    server_id: str,
) -> dict | None:
    """Convert a Plex session Metadata dict to a normalized now-playing item.
    Returns None if the session has no User (idle/transient sessions are skipped)."""
    user = s.get("User")
    if not user or not isinstance(user, dict):
        return None
    player = s.get("Player") or {}
    rating_key = rating_key_from_plex_session_dict(s) or ""
    session_sub = s.get("Session") or {}
    session_id_raw = session_sub.get("id") or rating_key
    view_offset_ms = s.get("viewOffset") or 0
    duration_ms = s.get("duration") or 0
    plex_type = (s.get("type") or "").lower()
    _plex_base = (app_url or "").rstrip("/")
    if _plex_base and server_id and rating_key:
        plex_item_url = f"{_plex_base}/web/index.html#!/server/{server_id}/details?key=/library/metadata/{rating_key}"
    else:
        plex_item_url = _plex_base
    return {
        "session_id": f"{instance_id}:{session_id_raw}",
        "instance_id": instance_id,
        "instance_label": instance_label,
        "service_type": "plex",
        "app_url": app_url,
        "server_id": server_id,
        "item_url": plex_item_url,
        "user_id": str(user.get("id") or ""),
        "user_name": (user.get("title") or "").strip(),
        "device_name": (player.get("title") or player.get("device") or "").strip(),
        "item": {
            "id": rating_key,
            "name": s.get("title") or rating_key,
            "type": _PLEX_TYPE_MAP.get(
                plex_type, plex_type.capitalize() if plex_type else "Unknown"
            ),
            "run_time_ticks": duration_ms * _PLEX_MS_TO_TICKS,
            "image_tag": "",
            "series_name": s.get("grandparentTitle") or "",
            "series_id": None,
            "index_number": s.get("index"),
            "parent_index_number": s.get("parentIndex"),
        },
        "position_ticks": view_offset_ms * _PLEX_MS_TO_TICKS,
        "is_paused": (player.get("state") or "").lower() == "paused",
        "play_method": "",
    }


async def refresh_now_playing_state(instance_ids: list[int] | None = None) -> dict:
    """Aggregate sessions from configured Emby, Jellyfin, and Plex instances; return {items: [...]}.
    If instance_ids is set, only those instances are included."""
    instances = await store_instances.list_instances()
    allowed_ids = set(instance_ids) if instance_ids else None
    active = [
        inst
        for inst in instances
        if inst.get("is_configured")
        and inst.get("active", True)
        and inst.get("id") is not None
        and (allowed_ids is None or inst.get("id") in allowed_ids)
    ]
    configs = await asyncio.gather(
        *[store_instances.get_instance_connection_config(inst["id"]) for inst in active]
    )

    emby_jellyfin = [
        (inst, cfg)
        for inst, cfg in zip(active, configs)
        if cfg and cfg[0] in ("emby", "jellyfin") and cfg[1] and cfg[2]
    ]
    plex_instances = [
        (inst, cfg)
        for inst, cfg in zip(active, configs)
        if cfg and cfg[0] == "plex" and cfg[1] and cfg[2]
    ]

    emby_sessions_list, plex_sessions_list = await asyncio.gather(
        asyncio.gather(
            *[
                emby_integration.get_sessions(
                    cfg[1], cfg[2], active_within_seconds=None
                )
                for _, cfg in emby_jellyfin
            ]
        ),
        asyncio.gather(
            *[
                plex_integration.get_sessions(cfg[1], cfg[2])
                for _, cfg in plex_instances
            ]
        ),
    )

    items = []

    for (inst, _cfg), sessions in zip(emby_jellyfin, emby_sessions_list):
        instance_id = inst["id"]
        instance_label = (inst.get("label") or str(instance_id)).strip() or str(
            instance_id
        )
        app_url = (inst.get("app_url") or "").strip()
        server_id = (inst.get("media_server_id") or "").strip()
        for s in sessions:
            if not isinstance(s, dict):
                continue
            item = _normalize_session(
                s, instance_id, instance_label, app_url, server_id
            )
            if item is not None:
                items.append(item)

    for (inst, _cfg), sessions in zip(plex_instances, plex_sessions_list):
        instance_id = inst["id"]
        instance_label = (inst.get("label") or str(instance_id)).strip() or str(
            instance_id
        )
        app_url = (inst.get("app_url") or "").strip()
        server_id = (inst.get("media_server_id") or "").strip()
        if sessions is None:
            # The server did not answer. Its streams are still running as far
            # as anyone knows, so leave both the display and the live rows
            # alone rather than reporting nothing and closing every session.
            continue
        for s in sessions:
            if not isinstance(s, dict):
                continue
            item = _normalize_plex_session(
                s, instance_id, instance_label, app_url, server_id
            )
            if item is not None:
                items.append(item)
        try:
            await store_plex_playback.process_live_poll(instance_id, sessions)
        except Exception as e:
            log.warning("Plex playback session poll instance_id=%s: %s", instance_id, e)

    global _last_plex_snapshot_rebuild
    if plex_instances:
        now_mono = time.monotonic()
        if (
            now_mono - _last_plex_snapshot_rebuild
            >= brein_config.SNAPSHOT_REBUILD_INTERVAL_SECONDS
        ):
            # Stamped before the work, not after: advancing only on success
            # meant a rebuild that keeps failing ran again on every poll, every
            # cache miss and every socket connect — the heaviest query in the
            # app, in the request path, at 10s intervals.
            _last_plex_snapshot_rebuild = now_mono
            try:
                await store_plex_dashboard_metrics.rebuild_snapshots()
                await brein_cache.clear_media_metrics_cache()
            except Exception as e:
                log.warning("Plex dashboard snapshot rebuild failed: %s", e)

    return {"items": items}


async def refresh_and_cache_now_playing() -> None:
    """Refresh now-playing from Emby, write to cache, and broadcast to WebSocket clients. Used on login and by the periodic task."""
    data = await refresh_now_playing_state()
    await brein_cache.set_cached(NOW_PLAYING_CACHE_KEY, data)
    await broadcast_now_playing(data)


async def _get_now_playing_cached(
    instance_ids: list[int] | None = None,
) -> dict | None:
    """Return now-playing data from cache if valid, or None on miss."""
    cached = await brein_cache.get_cached(NOW_PLAYING_CACHE_KEY)
    if cached is not None:
        if instance_ids:
            allowed = set(instance_ids)
            items = [
                i
                for i in (cached.get("items") or [])
                if i.get("instance_id") in allowed
            ]
            return {"items": items}
        return cached
    return None


def _parse_instance_ids_query(raw: list[str] | None) -> list[int] | None:
    """Parse query param list of instance IDs (e.g. '1,2' or repeated ?instance_id=1&instance_id=2) to list[int]."""
    if not raw:
        return None
    parsed: list[int] = []
    for x in raw:
        try:
            parsed.append(int(str(x).strip()))
        except ValueError:
            continue
    return parsed if parsed else None


@router.get("/api/now-playing")
async def api_now_playing(
    current_user: CurrentUser,
    instance_id: list[str] | None = Query(
        None, description="Filter by instance IDs (integers); omit for all."
    ),
):
    """Aggregate active sessions from configured Emby instances (who is watching what). Optionally filter by instance_id. Uses cache when valid."""
    instance_ids_parsed = _parse_instance_ids_query(instance_id)
    cached = await _get_now_playing_cached(instance_ids=instance_ids_parsed)
    if cached is not None:
        return cached
    data = await refresh_now_playing_state(instance_ids=instance_ids_parsed)
    if instance_ids_parsed is None:
        await brein_cache.set_cached(NOW_PLAYING_CACHE_KEY, data)
    return data


@router.websocket("/ws/now-playing")
async def websocket_now_playing(websocket: WebSocket) -> None:
    """WebSocket for now-playing updates. Requires JSON first message with token. Sends initial snapshot then server pushes updates via broadcast."""

    if len(_ws_connections) >= WS_MAX_CONNECTIONS:
        await websocket.close(code=1008)
        return
    await websocket.accept()

    # The upgrade request carries cookies, so a browser authenticated with the
    # session cookie needs no in-band token — which it could not supply
    # anyway, the cookie being httpOnly. The token message stays supported for
    # non-browser clients.
    cookie_token = websocket.cookies.get(web_auth.ACCESS_TOKEN_COOKIE_NAME)
    user = await web_auth.get_user_from_token(cookie_token) if cookie_token else None

    if user is None:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            token = json.loads(raw).get("token")
        except Exception:
            await websocket.close(code=WS_UNAUTHORIZED_CLOSE_CODE)
            return
        user = await web_auth.get_user_from_token(token)

    if user is None or user.disabled:
        await websocket.close(code=WS_UNAUTHORIZED_CLOSE_CODE)
        return
    _ws_connections.add(websocket)
    try:
        snapshot = await _get_now_playing_cached()
        if snapshot is None:
            snapshot = await refresh_now_playing_state()
            await brein_cache.set_cached(NOW_PLAYING_CACHE_KEY, snapshot)
        await websocket.send_text(json.dumps(snapshot))
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        _ws_connections.discard(websocket)


# Register for on-login refresh (extensible hook used by auth router).
web_on_login_tasks.ON_LOGIN_REFRESH_TASKS.append(refresh_and_cache_now_playing)
