"""Calendar API: unified Sonarr (episodes) + Radarr (movies) calendar."""

import asyncio
import logging
import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from brein.integrations.api import radarr as radarr_api
from brein.integrations.api import sonarr as sonarr_api
from brein.web import auth as web_auth
from brein.web.schemas import User
from brein.store import instances as store_instances

log = logging.getLogger(__name__)

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]

DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
DATE_PARAM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_to_yyyy_mm_dd(value: Any) -> str | None:
    """Extract YYYY-MM-DD from ISO string or date-like value."""
    if value is None:
        return None
    s = str(value).strip()
    m = DATE_ONLY_RE.match(s)
    if m:
        return m.group(0)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _extract_poster_url(images: list) -> str | None:
    """Return the remoteUrl for the first image whose coverType is 'poster'."""
    for img in images or []:
        if isinstance(img, dict) and img.get("coverType") == "poster":
            url = img.get("remoteUrl") or img.get("url")
            if url:
                return str(url)
    return None


def _normalize_sonarr_event(
    item: dict, instance_id: int, instance_label: str, instance_base_url: str = ""
) -> dict[str, Any] | None:
    """Convert Sonarr calendar item to unified event. Returns None if no valid date."""
    series = item.get("series") or {}
    air_date = item.get("airDate")
    date_str = _date_to_yyyy_mm_dd(air_date)
    if not date_str:
        return None
    title = (series.get("title") or "").strip() or "—"
    sn = item.get("seasonNumber")
    en = item.get("episodeNumber")
    ep_title = (item.get("title") or "").strip()
    if sn is not None and en is not None:
        subtitle = f"S{sn}E{en}" + (f" – {ep_title}" if ep_title else "")
    else:
        subtitle = ep_title or ""
    images = series.get("images") or []
    genres = [str(g) for g in (series.get("genres") or []) if g][:3]
    runtime_raw = item.get("runtime") or series.get("runtime")
    try:
        runtime = int(runtime_raw) if runtime_raw is not None else None
    except (TypeError, ValueError):
        runtime = None
    year_raw = series.get("year")
    try:
        year = int(year_raw) if year_raw is not None else None
    except (TypeError, ValueError):
        year = None
    overview_raw = (item.get("overview") or "").strip()
    overview = overview_raw[:300] if overview_raw else None
    series_overview_raw = (series.get("overview") or "").strip()
    series_overview = series_overview_raw[:300] if series_overview_raw else None
    title_slug = (series.get("titleSlug") or "").strip() or None
    return {
        "date": date_str,
        "type": "episode",
        "title": title,
        "subtitle": subtitle,
        "source": "sonarr",
        "instance_id": instance_id,
        "instance_label": instance_label,
        "instance_base_url": instance_base_url,
        "has_file": bool(item.get("hasFile")),
        "monitored": item.get("monitored", True),
        "poster_url": _extract_poster_url(images),
        "overview": overview,
        "series_overview": series_overview,
        "title_slug": title_slug,
        "runtime": runtime,
        "year": year,
        "genres": genres,
        "season_number": sn,
        "episode_number": en,
        "episode_title": ep_title or None,
        "network": (series.get("network") or "").strip() or None,
    }


def _collect_release_types(item: dict, movie: dict) -> list[str]:
    """Return release type labels present in either item or movie dict."""
    types = []
    if item.get("digitalRelease") or movie.get("digitalRelease"):
        types.append("Digital")
    if item.get("physicalRelease") or movie.get("physicalRelease"):
        types.append("Physical")
    if item.get("inCinemas") or movie.get("inCinemas"):
        types.append("Cinema")
    return types


def _normalize_radarr_event(
    item: dict,
    instance_id: int,
    instance_label: str,
    instance_base_url: str = "",
    start: str = "",
    end: str = "",
) -> dict[str, Any] | None:
    """Convert Radarr calendar item to unified event. Returns None if no valid date.

    A movie has up to three release dates, and Radarr lists it because one
    of them falls in the window asked for. The event goes on the first one
    that does, since a fixed preference for the digital date put a cinema
    release this week on a digital date months away — outside the window,
    and so off the calendar. Without a window, or with none of the dates in
    it, the old preference stands.
    """
    movie = item.get("movie") or item
    title = (movie.get("title") or item.get("title") or "").strip() or "—"
    dates = [
        _date_to_yyyy_mm_dd(value)
        for value in (
            item.get("digitalRelease"),
            item.get("physicalRelease"),
            item.get("inCinemas"),
            movie.get("digitalRelease"),
            movie.get("physicalRelease"),
            movie.get("inCinemas"),
        )
    ]
    date_str = None
    if start and end:
        date_str = next((d for d in dates if d and start <= d <= end), None)
    if date_str is None:
        date_str = next((d for d in dates if d), None)
    if not date_str:
        return None
    subtitle = " / ".join(_collect_release_types(item, movie))
    images = movie.get("images") or item.get("images") or []
    genres = [str(g) for g in (movie.get("genres") or item.get("genres") or []) if g][
        :3
    ]
    runtime_raw = movie.get("runtime") or item.get("runtime")
    try:
        runtime = int(runtime_raw) if runtime_raw is not None else None
    except (TypeError, ValueError):
        runtime = None
    year_raw = movie.get("year") or item.get("year")
    try:
        year = int(year_raw) if year_raw is not None else None
    except (TypeError, ValueError):
        year = None
    overview_raw = (movie.get("overview") or item.get("overview") or "").strip()
    overview = overview_raw[:300] if overview_raw else None
    return {
        "date": date_str,
        "type": "movie",
        "title": title,
        "subtitle": subtitle,
        "source": "radarr",
        "instance_id": instance_id,
        "instance_label": instance_label,
        "has_file": bool(item.get("hasFile") or movie.get("hasFile")),
        "monitored": item.get("monitored", movie.get("monitored", True)),
        "poster_url": _extract_poster_url(images),
        "overview": overview,
        "runtime": runtime,
        "year": year,
        "genres": genres,
        "studio": (movie.get("studio") or item.get("studio") or "").strip() or None,
        "certification": (
            movie.get("certification") or item.get("certification") or ""
        ).strip()
        or None,
        "tmdb_id": movie.get("tmdbId") or item.get("tmdbId"),
        "instance_base_url": instance_base_url,
    }


async def _fetch_sonarr_events(
    instance_id: int,
    base_url: str,
    api_key: str,
    label: str,
    start: str,
    end: str,
    link_url: str = "",
) -> list[dict[str, Any]]:
    ok, data = await sonarr_api.get_calendar(
        base_url, api_key, start, end, unmonitored=False
    )
    if not ok or not data:
        return []
    return [
        ev
        for item in data
        if isinstance(item, dict)
        for ev in [
            _normalize_sonarr_event(item, instance_id, label, link_url or base_url)
        ]
        if ev
    ]


async def _fetch_radarr_events(
    instance_id: int,
    base_url: str,
    api_key: str,
    label: str,
    start: str,
    end: str,
    link_url: str = "",
) -> list[dict[str, Any]]:
    ok, data = await radarr_api.get_calendar(
        base_url, api_key, start, end, unmonitored=False
    )
    if not ok or not data:
        return []
    return [
        ev
        for item in data
        if isinstance(item, dict)
        for ev in [
            _normalize_radarr_event(
                item, instance_id, label, link_url or base_url, start, end
            )
        ]
        if ev
    ]


async def _fetch_instance_events(
    inst: dict, start: str, end: str
) -> list[dict[str, Any]]:
    instance_id = inst.get("id")
    if instance_id is None:
        return []
    try:
        instance_id = int(instance_id)
    except (TypeError, ValueError):
        return []
    cfg = await store_instances.get_instance_connection_config(instance_id)
    if not cfg:
        return []
    service_type, base_url, api_key = cfg
    if not base_url or not api_key:
        return []
    label = (inst.get("label") or str(instance_id)).strip() or str(instance_id)
    # Two different URLs: base_url is how Brein reaches the service, link_url
    # is where a person is sent — the external address when one is set, and
    # the internal one otherwise. They are the same on a LAN-only install and
    # very much not behind a reverse proxy.
    link_url = (inst.get("app_url") or "").strip()
    if service_type == "sonarr":
        return await _fetch_sonarr_events(
            instance_id, base_url, api_key, label, start, end, link_url
        )
    if service_type == "radarr":
        return await _fetch_radarr_events(
            instance_id, base_url, api_key, label, start, end, link_url
        )
    return []


@router.get("/api/calendar")
async def api_calendar(
    _user: CurrentUser,
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> list[dict[str, Any]]:
    """Return unified calendar events (Sonarr episodes + Radarr movies) for the date range."""
    if not DATE_PARAM_RE.match(start) or not DATE_PARAM_RE.match(end):
        raise HTTPException(status_code=400, detail="start and end must be YYYY-MM-DD")
    instances = await store_instances.list_instances()
    calendar_instances = [
        i
        for i in instances
        if i.get("is_configured")
        and i.get("active", True)
        and (i.get("service_type") or "").lower() in ("sonarr", "radarr")
    ]
    results = await asyncio.gather(
        *[_fetch_instance_events(inst, start, end) for inst in calendar_instances],
        return_exceptions=True,
    )
    events: list[dict[str, Any]] = []
    for inst, r in zip(calendar_instances, results):
        if isinstance(r, list):
            events.extend(r)
        else:
            # One instance failing must not empty the calendar, but it must
            # not vanish without a trace either.
            log.warning(
                "Calendar: dropped events of instance %s (%s): %r",
                inst.get("id"),
                inst.get("label") or inst.get("service_type"),
                r,
            )
    events.sort(key=lambda e: (e.get("date") or "", e.get("title") or ""))
    return events
