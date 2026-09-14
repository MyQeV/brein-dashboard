"""SABnzbd instance router — queue, history, pause, resume, speed limit."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from brein import config as brein_config
from brein.db import get_session
from brein.integrations.api import sabnzbd as sabnzbd_api
from brein.store import instances as store_instances
from brein.store import sabnzbd_stats as store_sabnzbd_stats
from brein.web import auth as web_auth
from brein.web.schemas import User

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
WebUser = Annotated[User, Depends(web_auth.get_current_user_cookie_or_bearer)]
# NOTE: cookie-or-bearer, unlike the bearer-only `AdminUser` in the other
# routers. These endpoints are driven straight from HTMX attributes in the
# downloader fragments, which send no Authorization header.
AdminUserCookieOrBearer = Annotated[
    User, Depends(web_auth.get_current_admin_user_cookie_or_bearer)
]
Session = Annotated[AsyncSession, Depends(get_session)]


async def _get_sabnzbd_config(instance_id: int) -> tuple[str, str]:
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Instance not found")
    service_type, base_url, api_key = cfg
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="Configure host and API key first")
    if service_type != "sabnzbd":
        raise HTTPException(status_code=400, detail="Not a SABnzbd instance")
    return base_url, api_key


@router.get("/api/instances/{instance_id}/sabnzbd/speedlimit")
async def api_instance_sabnzbd_speedlimit(instance_id: int, current_user: CurrentUser):
    base_url, api_key = await _get_sabnzbd_config(instance_id)
    ok, speedlimit = await sabnzbd_api.get_speed_limit_config(base_url, api_key)
    if not ok:
        # Returning 100 here made an unreachable SABnzbd indistinguishable from
        # a server genuinely reporting no limit.
        raise HTTPException(status_code=502, detail="SABnzbd unreachable")
    return JSONResponse({"speedlimit": speedlimit})


@router.get("/api/instances/{instance_id}/sabnzbd/history/for-date")
async def api_instance_sabnzbd_history_for_date(
    instance_id: int,
    current_user: CurrentUser,
    date_str: str = Query(..., alias="date"),
):
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format, expected YYYY-MM-DD"
        )
    base_url, api_key = await _get_sabnzbd_config(instance_id)
    result = []
    page_size = 100
    offset = 0
    while True:
        ok, items = await sabnzbd_api.get_history_filtered(
            base_url, api_key, limit=page_size, start=offset
        )
        if not ok:
            raise HTTPException(status_code=502, detail="Could not reach SABnzbd")
        if not items:
            break
        done = False
        for item in items:
            completed_ts = item.get("completed") or 0
            if not completed_ts:
                continue
            item_date = date.fromtimestamp(completed_ts)
            if item_date == target:
                result.append(
                    {
                        "name": item.get("name") or item.get("nzb_name") or "",
                        "size": item.get("size") or "",
                        "status": item.get("status") or "",
                        "category": item.get("cat") or item.get("category") or "",
                        "completed_ts": completed_ts,
                    }
                )
            elif item_date < target:
                done = True
                break
        if done or len(items) < page_size:
            break
        offset += page_size
    return JSONResponse(result)


@router.get("/api/instances/{instance_id}/sabnzbd/ping")
async def api_instance_sabnzbd_ping(instance_id: int, current_user: WebUser):
    base_url, api_key = await _get_sabnzbd_config(instance_id)
    ok, message = await sabnzbd_api.test_connection(base_url, api_key)
    return {"ok": ok, "message": message}


@router.post("/api/instances/{instance_id}/sabnzbd/restart")
async def api_instance_sabnzbd_restart(
    instance_id: int, current_user: AdminUserCookieOrBearer
):
    base_url, api_key = await _get_sabnzbd_config(instance_id)
    ok, msg = await sabnzbd_api.restart(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Restart failed")
    return {"ok": True, "message": msg}


@router.get("/api/instances/{instance_id}/sabnzbd/stats/daily")
async def api_instance_sabnzbd_stats_daily(
    instance_id: int,
    current_user: WebUser,
    start: date | None = Query(None),
    end: date | None = Query(None),
):
    """Daily download volume for the SABnzbd instance (stored snapshots).

    Response contract:
    - ``labels`` and ``gigabytes`` have the **same length**; index ``i`` is one calendar day.
    - Days are **inclusive** from ``start`` through ``end`` in **Brein's configured timezone**
      (``TZ`` env var), not the client's local zone.
    - Each ``gigabytes[i]`` is decimal GB (10⁹ bytes). Prefer SABnzbd's ``servers[*].daily``
      timeline from the latest stored snapshot; otherwise day-over-day ``bytes_total``
      deltas from snapshots (see store).

    Query params: ``start`` and ``end`` are ISO dates (``YYYY-MM-DD``). If omitted,
    ``end`` defaults to today (app timezone) and ``start`` to 13 days earlier (14 days inclusive).
    """
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Instance not found")
    service_type, _, _ = cfg
    if service_type != "sabnzbd":
        raise HTTPException(status_code=404, detail="Instance not found")
    tz_end = brein_config.get_local_date()
    if end is None:
        end = tz_end
    if start is None:
        start = end - timedelta(days=13)
    if start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    labels, gigabytes = await store_sabnzbd_stats.get_daily_series_gigabytes(
        instance_id, start, end
    )
    return {"labels": labels, "gigabytes": gigabytes}
