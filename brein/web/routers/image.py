"""Emby image proxy API."""

import base64
import logging
import re
from typing import Annotated
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from brein import cache as brein_cache
from brein.integrations.api.base import DEFAULT_HTTP_TIMEOUT
from brein.integrations.api.emby import _auth_headers
from brein.web import auth as web_auth
from brein.web.schemas import User
from brein.store import instances as store_instances

router = APIRouter()
log = logging.getLogger(__name__)
# Cookie or Bearer so <img src> requests (which send cookies, not Bearer) succeed
ImageUser = Annotated[User, Depends(web_auth.get_current_user_cookie_or_bearer)]

IMAGE_CACHE_TTL = 300
# The only Radarr/Sonarr path the image proxy will fetch. Anything else on
# the server would have gone out with the API key attached.
_ARR_IMAGE_PREFIX = "/MediaCover/"

_HEX_RE = re.compile(r"^[0-9a-fA-F]{1,64}$")
# Emby and Jellyfin image tags are "<md5>_<ticks>", not bare hex; the tag is
# only ever forwarded as a query parameter, so the underscore and digits are
# harmless — rejecting them 400'd every movie and Live TV poster.
_TAG_RE = re.compile(r"^[0-9a-fA-F]{1,64}(_[0-9]{1,20})?$")
_VALID_IMAGE_TYPES = frozenset(
    {
        "Primary",
        "Art",
        "Banner",
        "Logo",
        "Thumb",
        "Disc",
        "Box",
        "Screenshot",
        "Menu",
        "Chapter",
        "BoxRear",
        "Profile",
    }
)


@router.get("/api/instances/{instance_id}/image")
async def api_instance_image(
    instance_id: int,
    current_user: ImageUser,
    item_id: str,
    tag: str = "",
    type: str = "Primary",
    max_width: int | None = None,
    context: str = "item",
):
    """Proxy Emby item/user image so the browser does not need the API key. Responses are cached."""
    if not _HEX_RE.match(item_id):
        raise HTTPException(status_code=400, detail="Invalid item_id")
    if tag and not _TAG_RE.match(tag):
        raise HTTPException(status_code=400, detail="Invalid tag")
    if type not in _VALID_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")
    if context not in ("item", "user"):
        raise HTTPException(status_code=400, detail="Invalid context")
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Instance not found")
    service_type, base_url, api_key = cfg
    if service_type not in ("emby", "jellyfin", "plex") or not base_url or not api_key:
        raise HTTPException(status_code=404, detail="Not supported or not configured")
    cache_key = f"img:{instance_id}:{context}:{item_id}:{tag}:{type}:{max_width or ''}"
    cached = await brein_cache.get_cached(cache_key)
    if isinstance(cached, dict) and "b64" in cached and "content_type" in cached:
        try:
            return Response(
                content=base64.b64decode(cached["b64"]),
                media_type=cached["content_type"],
                headers={"Cache-Control": f"public, max-age={IMAGE_CACHE_TTL}"},
            )
        except Exception:
            # Unusable cache entry (truncated or wrong shape): fall through and
            # re-fetch the image rather than failing the request.
            log.debug("Discarding unusable cached image entry", exc_info=True)
    base = (base_url or "").strip().rstrip("/")
    if service_type == "plex":
        url = urljoin(base + "/", f"library/metadata/{item_id}/thumb")
        req_headers = {"X-Plex-Token": api_key, "Accept": "image/jpeg, image/*"}
        req_params: dict = {}
    else:
        path = (
            f"Users/{item_id}/Images/{type}"
            if context == "user"
            else f"Items/{item_id}/Images/{type}"
        )
        req_headers = _auth_headers(api_key)
        req_params = {}
        if tag:
            req_params["Tag"] = tag
        if max_width is not None:
            req_params["MaxWidth"] = str(max_width)
        url = urljoin(base + "/", path)
    try:
        from brein.integrations.api.base import get_http_client

        r = await get_http_client().get(
            url, params=req_params, headers=req_headers, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail="Image not found")
        media_type = r.headers.get("content-type") or "image/jpeg"
        # Serve only what the upstream says is an image: this response goes out
        # from Brein's own origin. _proxy_arr_image already guards this way.
        if not media_type.startswith("image/"):
            raise HTTPException(
                status_code=502, detail="Upstream did not return an image"
            )
        await brein_cache.set_cached(
            cache_key,
            {
                "b64": base64.b64encode(r.content).decode(),
                "content_type": media_type,
            },
            ttl_seconds=IMAGE_CACHE_TTL,
        )
        return Response(
            content=r.content,
            media_type=media_type,
            headers={"Cache-Control": f"public, max-age={IMAGE_CACHE_TTL}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        log.warning("api_instance_image error %s: %s", url, e)
        raise HTTPException(status_code=502, detail="Failed to fetch image")


async def _proxy_arr_image(instance_id: int, path: str, service_type: str) -> Response:
    """Proxy image from Radarr or Sonarr instance. Path must be under /MediaCover/."""
    from posixpath import normpath
    from urllib.parse import parse_qs, unquote, urlsplit

    if not path or not path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    if ".." in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    parsed = urlsplit(path)
    # Checked decoded and normalised: the server would resolve %2e%2e itself.
    if not normpath(unquote(parsed.path)).startswith(_ARR_IMAGE_PREFIX):
        raise HTTPException(status_code=400, detail="Invalid path")
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Instance not found")
    stype, base_url, api_key = cfg
    if stype != service_type or not base_url or not api_key:
        raise HTTPException(status_code=404, detail="Not supported or not configured")
    cache_key = f"img:{service_type}:{instance_id}:{path}"
    cached = await brein_cache.get_cached(cache_key)
    if isinstance(cached, dict) and "b64" in cached and "content_type" in cached:
        try:
            return Response(
                content=base64.b64decode(cached["b64"]),
                media_type=cached["content_type"],
                headers={"Cache-Control": f"public, max-age={IMAGE_CACHE_TTL}"},
            )
        except Exception:
            # Unusable cache entry (truncated or wrong shape): fall through and
            # re-fetch the image rather than failing the request.
            log.debug("Discarding unusable cached image entry", exc_info=True)
    base = (base_url or "").strip().rstrip("/")
    url = base + parsed.path
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    params["apikey"] = api_key
    try:
        from brein.integrations.api.base import get_http_client

        r = await get_http_client().get(
            url, params=params, timeout=DEFAULT_HTTP_TIMEOUT
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail="Image not found")
        media_type = (
            r.headers.get("content-type", "").split(";")[0].strip() or "image/jpeg"
        )
        if not media_type.startswith("image/"):
            raise HTTPException(
                status_code=502, detail="Upstream returned non-image content"
            )
        await brein_cache.set_cached(
            cache_key,
            {
                "b64": base64.b64encode(r.content).decode(),
                "content_type": media_type,
            },
            ttl_seconds=IMAGE_CACHE_TTL,
        )
        return Response(
            content=r.content,
            media_type=media_type,
            headers={"Cache-Control": f"public, max-age={IMAGE_CACHE_TTL}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        log.warning("_proxy_arr_image error %s: %s", url, e)
        raise HTTPException(status_code=502, detail="Failed to fetch image")


@router.get("/api/instances/{instance_id}/radarr/image")
async def api_instance_radarr_image(
    instance_id: int,
    path: str,
    _auth: ImageUser,
):
    """Proxy Radarr MediaCover image. Responses are cached."""
    return await _proxy_arr_image(instance_id, path, "radarr")


@router.get("/api/instances/{instance_id}/sonarr/image")
async def api_instance_sonarr_image(
    instance_id: int,
    path: str,
    _auth: ImageUser,
):
    """Proxy Sonarr MediaCover image. Responses are cached."""
    return await _proxy_arr_image(instance_id, path, "sonarr")
