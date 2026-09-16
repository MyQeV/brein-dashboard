"""Dashboard stats and HTMX fragment API."""

import asyncio
import json
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from brein import cache as brein_cache
from brein import config as brein_config
from brein.store.metrics_activity import get_all_metrics as _emby_get_all_metrics
from brein.store.metrics_playback import (
    get_all_sessions as _emby_get_all_sessions,
    get_item_sessions as _emby_get_item_sessions,
    get_media_type_sessions as _emby_get_media_type_sessions,
    get_time_sessions as _emby_get_time_sessions,
    get_user_sessions as _emby_get_user_sessions,
)
from brein.store import jellyfin_dashboard_metrics as store_jellyfin_metrics
from brein.store import plex_dashboard_metrics as store_plex_metrics
from brein.web import auth as web_auth
from brein.web.dependencies import require_instance_config
from brein.web.schemas import User
from brein.store import dashboard_insights as store_insights
from brein.store import instances as store_instances


class _EmbyMetrics:
    """Namespace shim preserving store_emby_metrics.* call sites."""

    get_all_metrics = staticmethod(_emby_get_all_metrics)
    get_all_sessions = staticmethod(_emby_get_all_sessions)
    get_user_sessions = staticmethod(_emby_get_user_sessions)
    get_item_sessions = staticmethod(_emby_get_item_sessions)
    get_media_type_sessions = staticmethod(_emby_get_media_type_sessions)
    get_time_sessions = staticmethod(_emby_get_time_sessions)


store_emby_metrics = _EmbyMetrics()

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]


def _parse_date_range(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    """Resolve and validate start/end date strings (YYYY-MM-DD). Raises HTTPException on invalid format."""
    today = brein_config.get_local_date()
    if end_date is None:
        end_date = today.isoformat()
    if start_date is None:
        start_date = (today - timedelta(days=7)).isoformat()
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="start_date and end_date must be YYYY-MM-DD format.",
        )
    if start > end:
        raise HTTPException(
            status_code=400, detail="start_date must not be after end_date"
        )
    return start_date, end_date


def _parse_instance_ids(instance_ids: str | None) -> int | list[int] | None:
    """Parse comma-separated instance IDs into a single int, list, or None.

    A filter that parses to nothing is rejected rather than dropped: an empty
    filter means "every instance", which is the opposite of what a caller
    asking for `instance_ids=abc` wants — and is how `_user_instance_filter`
    already treats the same situation.
    """
    if not instance_ids or not instance_ids.strip():
        return None
    parsed: list[int] = []
    for x in instance_ids.split(","):
        x = x.strip()
        if not x:
            continue
        try:
            parsed.append(int(x))
        except ValueError:
            # Not skipped: "1,abc" narrowed to [1] served a filter the caller
            # never asked for, and only an all-garbage value was refused.
            raise HTTPException(
                status_code=400,
                detail="instance_ids must be comma-separated integers.",
            ) from None
    if not parsed:
        raise HTTPException(
            status_code=400, detail="instance_ids must be comma-separated integers."
        )
    return parsed[0] if len(parsed) == 1 else parsed


def _parse_user_ids(user_ids: str | None) -> list[str] | None:
    """Parse comma-separated user keys into a list or None.

    The frontend sends composite keys in the form "instance_id:user_id" (e.g. "1:12345").
    The instance prefix is preserved so the store layer can scope queries per instance,
    preventing cross-instance user ID collisions.
    """
    if not user_ids or not user_ids.strip():
        return None
    parts = [u.strip() for u in user_ids.split(",") if u.strip()]
    return parts or None


def _cache_key(
    start_date: str,
    end_date: str,
    instance_ids: int | list[int] | None,
    user_ids: list[str] | None,
) -> str:
    """A cache key built from the parsed filters, not the raw query strings.

    Joining the raw strings with ":" let two different scopes collide, because
    the values contain ":" themselves — `instance_ids=1:2&user_ids=3` (both
    malformed, so both dropped) keyed the same as `instance_ids=1&user_ids=2:3`,
    and whichever ran first served the other its answer for the whole TTL.
    """
    return json.dumps([start_date, end_date, instance_ids, user_ids], sort_keys=True)


@router.get("/api/dashboard/sessions")
async def api_dashboard_sessions(
    current_user: CurrentUser,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    instance_ids: str | None = Query(None),
    user_ids: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """All playback sessions in the date range matching active filters.

    Capped per backend, newest first. The cap was fixed at 500 and invisible,
    so a caller totalling the rows silently reported the newest slice of a
    long range as if it were the whole of it.
    """
    start_date, end_date = _parse_date_range(start_date, end_date)
    instance_ids_parsed = _parse_instance_ids(instance_ids)
    user_ids_parsed = _parse_user_ids(user_ids)
    emby_sessions, jellyfin_sessions, plex_sessions = await asyncio.gather(
        store_emby_metrics.get_all_sessions(
            start_date, end_date, instance_ids_parsed, user_ids_parsed, limit=limit
        ),
        store_jellyfin_metrics.get_all_sessions(
            start_date, end_date, instance_ids_parsed, user_ids_parsed, limit=limit
        ),
        store_plex_metrics.get_all_sessions(
            start_date, end_date, instance_ids_parsed, user_ids_parsed, limit=limit
        ),
    )
    combined: list[dict[str, Any]] = (
        _tag_backend(emby_sessions, "emby")
        + _tag_backend(jellyfin_sessions, "jellyfin")
        + _tag_backend(plex_sessions, "plex")
    )
    combined.sort(key=lambda r: r["played_at"], reverse=False)
    return combined


def _tag_backend(rows: list[dict[str, Any]], backend: str) -> list[dict[str, Any]]:
    """Stamp which media backend a session row came from.

    The session endpoints run one query per backend, each with its own LIMIT,
    and concatenate — so whether anything was truncated is a question about an
    arm, not about the total or about any one instance. Only the router knows
    which arm a row came from, and the client needs it to tell a complete list
    from a capped one: counting per instance under-reports (one capped arm is
    split across its instances' labels) and counting the total over-reports
    (two arms together can pass the limit with neither of them cut).
    """
    for row in rows:
        row["backend"] = backend
    return rows


def _sum_by_label(
    rows: list[dict[str, Any]],
    value_key: str,
    limit: int,
    label_key: str = "label",
) -> list[dict[str, Any]]:
    """Collapse rows sharing a title into one.

    A series or film present on two media servers arrives as one row per
    server. Left split, the same title takes two slices of the same doughnut
    while the drill-down — which matches on the label — reports the combined
    sessions for either.
    """
    totals: dict[str, int] = {}
    for row in rows:
        label = str(row.get(label_key) or "")
        if not label:
            continue
        totals[label] = totals.get(label, 0) + int(row.get(value_key) or 0)
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [{label_key: label, value_key: value} for label, value in ranked]


def _merge_metrics(
    emby: dict[str, Any], jellyfin: dict[str, Any], plex: dict[str, Any]
) -> dict[str, Any]:
    """Merge Emby, Jellyfin, and Plex get_all_metrics results into a single unified dict."""
    total_plays = emby["total_plays"] + jellyfin["total_plays"] + plex["total_plays"]
    total_watch_time = (
        emby["total_watch_time_seconds"]
        + jellyfin["total_watch_time_seconds"]
        + plex["total_watch_time_seconds"]
    )

    e_hour = {r["hour"]: r["total_seconds"] for r in emby["streaming_by_hour"]}
    j_hour = {r["hour"]: r["total_seconds"] for r in jellyfin["streaming_by_hour"]}
    p_hour = {r["hour"]: r["total_seconds"] for r in plex["streaming_by_hour"]}
    e_wd = {r["weekday"]: r["total_seconds"] for r in emby["activity_by_weekday"]}
    j_wd = {r["weekday"]: r["total_seconds"] for r in jellyfin["activity_by_weekday"]}
    p_wd = {r["weekday"]: r["total_seconds"] for r in plex["activity_by_weekday"]}
    emby_mt = emby["watch_time_by_media_type"]
    jf_mt = jellyfin["watch_time_by_media_type"]
    plex_mt = plex["watch_time_by_media_type"]

    return {
        "start_date": emby["start_date"],
        "end_date": emby["end_date"],
        "total_plays": total_plays,
        "total_watch_time_seconds": total_watch_time,
        "avg_session_seconds": round(total_watch_time / total_plays)
        if total_plays > 0
        else 0,
        "active_users_count": emby["active_users_count"]
        + jellyfin["active_users_count"]
        + plex["active_users_count"],
        "plays_per_user": sorted(
            emby["plays_per_user"]
            + jellyfin["plays_per_user"]
            + plex["plays_per_user"],
            key=lambda r: r["plays"],
            reverse=True,
        ),
        "watch_time_per_user": sorted(
            emby["watch_time_per_user"]
            + jellyfin["watch_time_per_user"]
            + plex["watch_time_per_user"],
            key=lambda r: r["total_seconds"],
            reverse=True,
        ),
        # These rows are titled `display_label`, not `label`, so they need the
        # key naming: summing them under "label" collapsed every item into one
        # empty-titled row carrying the grand total.
        "most_watched_items": _sum_by_label(
            emby["most_watched_items"]
            + jellyfin["most_watched_items"]
            + plex["most_watched_items"],
            "plays",
            20,
            label_key="display_label",
        ),
        "total_watched_movies": emby["total_watched_movies"]
        + jellyfin["total_watched_movies"]
        + plex["total_watched_movies"],
        "total_watched_episodes": emby["total_watched_episodes"]
        + jellyfin["total_watched_episodes"]
        + plex["total_watched_episodes"],
        "total_watched_series": emby["total_watched_series"]
        + jellyfin["total_watched_series"]
        + plex["total_watched_series"],
        "total_watched_live_tv": emby["total_watched_live_tv"]
        + jellyfin["total_watched_live_tv"]
        + plex["total_watched_live_tv"],
        "watch_time_by_media_type": {
            k: emby_mt.get(k, 0) + jf_mt.get(k, 0) + plex_mt.get(k, 0)
            for k in set(emby_mt) | set(jf_mt) | set(plex_mt)
        },
        "watch_time_per_series": _sum_by_label(
            emby["watch_time_per_series"]
            + jellyfin["watch_time_per_series"]
            + plex["watch_time_per_series"],
            "total_seconds",
            50,
        ),
        "watch_time_per_movie": _sum_by_label(
            emby["watch_time_per_movie"]
            + jellyfin["watch_time_per_movie"]
            + plex["watch_time_per_movie"],
            "total_seconds",
            50,
        ),
        "streaming_by_hour": [
            {
                "hour": h,
                "total_seconds": e_hour.get(h, 0) + j_hour.get(h, 0) + p_hour.get(h, 0),
            }
            for h in range(24)
        ],
        "activity_by_weekday": [
            {
                "weekday": d,
                "total_seconds": e_wd.get(d, 0) + j_wd.get(d, 0) + p_wd.get(d, 0),
            }
            for d in range(7)
        ],
        "watch_time_per_user_per_day": sorted(
            (emby.get("watch_time_per_user_per_day") or [])
            + (jellyfin.get("watch_time_per_user_per_day") or [])
            + (plex.get("watch_time_per_user_per_day") or []),
            key=lambda r: r["date"],
        ),
    }


@router.get("/api/dashboard/downloads")
async def api_dashboard_downloads(current_user: CurrentUser) -> dict:
    """Download totals per configured SABnzbd instance.

    Returns raw bytes; formatting is the client's job. This data was only
    reachable by rendering the Jinja downloads fragment.
    """
    from brein.store import sabnzbd_stats as store_sabnzbd_stats

    instances = await store_instances.list_instances()
    cards = []
    for inst in instances:
        if (inst.get("service_type") or "").lower() != "sabnzbd":
            continue
        if not inst.get("is_configured"):
            continue
        raw_id = inst.get("id")
        if raw_id is None:
            continue
        try:
            instance_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        snapshot = await store_sabnzbd_stats.get_latest_snapshot(instance_id)
        cards.append(
            {
                "instance_id": instance_id,
                "label": inst.get("label") or str(instance_id),
                "collected_at": (
                    snapshot.collected_at.isoformat() if snapshot else None
                ),
                "bytes_today": getattr(snapshot, "bytes_today", None),
                "bytes_week": getattr(snapshot, "bytes_week", None),
                "bytes_month": getattr(snapshot, "bytes_month", None),
                "bytes_total": getattr(snapshot, "bytes_total", None),
            }
        )
    return {"downloads": cards}


@router.get("/api/dashboard/downloads-daily")
async def api_dashboard_downloads_daily(
    current_user: CurrentUser,
    instance_id: int = Query(...),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Per-day download volume in gigabytes, for one SABnzbd instance.

    The old dashboard drew this from the Jinja fragment; the series itself has
    always come from `sabnzbd_stats`, which had no JSON route until now.
    """
    from brein.store import sabnzbd_stats as store_sabnzbd_stats

    await require_instance_config(
        instance_id, "sabnzbd", detail="Not a SABnzbd instance"
    )
    end = brein_config.get_local_date()
    start = end - timedelta(days=days - 1)
    labels, gigabytes = await store_sabnzbd_stats.get_daily_series_gigabytes(
        instance_id, start, end
    )
    return {"labels": labels, "gigabytes": gigabytes}


@router.get("/api/dashboard/concurrency")
async def api_dashboard_concurrency(
    current_user: CurrentUser,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    instance_ids: str | None = Query(None),
    user_ids: str | None = Query(None),
) -> dict[str, Any]:
    """Peak simultaneous streams per day, and the highest of them."""
    start_date, end_date = _parse_date_range(start_date, end_date)
    instance_ids_parsed = _parse_instance_ids(instance_ids)
    user_ids_parsed = _parse_user_ids(user_ids)

    cache_key = f"concurrency:{_cache_key(start_date, end_date, instance_ids_parsed, user_ids_parsed)}"
    cached = await brein_cache.get_insight_cached(cache_key)
    if cached is not None:
        return cached

    rows = await store_insights.get_concurrency_by_day(
        start_date,
        end_date,
        instance_ids_parsed,
        user_ids_parsed,
    )
    best = max(rows, key=lambda r: r["peak"], default=None)
    payload = {
        "per_day": rows,
        "peak": best["peak"] if best else 0,
        "peak_date": best["date"] if best else "",
    }
    await brein_cache.set_insight_cached(cache_key, payload)
    return payload


@router.get("/api/dashboard/idle-users")
async def api_dashboard_idle_users(
    current_user: CurrentUser,
    days: int = Query(30, ge=1, le=3650),
    instance_ids: str | None = Query(None),
) -> dict[str, Any]:
    """Users who have not played anything for `days`, or ever."""
    instance_ids_parsed = _parse_instance_ids(instance_ids)
    cache_key = f"idle:{_cache_key(str(days), '', instance_ids_parsed, None)}"
    rows = await brein_cache.get_insight_cached(cache_key)
    if rows is None:
        rows = await store_insights.get_idle_users(days, instance_ids_parsed)
        await brein_cache.set_insight_cached(cache_key, rows)
    return {"days": days, "users": rows}


@router.get("/api/dashboard/library-unwatched")
async def api_dashboard_library_unwatched(
    current_user: CurrentUser,
    item_type: str | None = Query(None, description="Movie or Episode"),
    instance_ids: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    include_summary: bool = Query(
        True, description="Set false when the caller already has the summary"
    ),
) -> dict[str, Any]:
    """Library totals against what has never been played, plus the titles.

    The summary is an anti-join over every library row, so the client that
    only wants a title list asks for it to be skipped rather than making the
    page pay for it twice.
    """
    if item_type and item_type.title() not in ("Movie", "Episode"):
        raise HTTPException(
            status_code=400, detail="item_type must be Movie or Episode."
        )
    instance_ids_parsed = _parse_instance_ids(instance_ids)

    summary: list[dict[str, Any]] = []
    if include_summary:
        summary_key = f"unwatched:{_cache_key('', '', instance_ids_parsed, None)}"
        cached = await brein_cache.get_insight_cached(summary_key)
        if cached is None:
            cached = await store_insights.get_unwatched_summary(instance_ids_parsed)
            await brein_cache.set_insight_cached(summary_key, cached)
        summary = cached

    items: list[dict[str, Any]] = []
    if item_type:
        items_key = "unwatched_items:" + _cache_key(
            item_type.title(), str(limit), instance_ids_parsed, None
        )
        cached_items = await brein_cache.get_insight_cached(items_key)
        if cached_items is None:
            cached_items = await store_insights.get_unwatched_items(
                item_type, instance_ids_parsed, limit
            )
            await brein_cache.set_insight_cached(items_key, cached_items)
        items = cached_items
    return {"summary": summary, "items": items}


@router.get("/api/dashboard/media-metrics")
async def api_dashboard_media_metrics(
    current_user: CurrentUser,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    instance_ids: str | None = Query(None),
    user_ids: str | None = Query(None),
):
    """Merged Emby + Jellyfin + Plex activity metrics from pre-computed snapshots."""
    start_date, end_date = _parse_date_range(start_date, end_date)
    instance_ids_parsed = _parse_instance_ids(instance_ids)
    user_ids_parsed = _parse_user_ids(user_ids)

    cache_key = _cache_key(start_date, end_date, instance_ids_parsed, user_ids_parsed)
    cached = await brein_cache.get_media_metrics_cached(cache_key)
    if cached is not None:
        return cached

    emby_data, jellyfin_data, plex_data = await asyncio.gather(
        store_emby_metrics.get_all_metrics(
            start_date, end_date, instance_ids_parsed, user_ids_parsed
        ),
        store_jellyfin_metrics.get_all_metrics(
            start_date, end_date, instance_ids_parsed, user_ids_parsed
        ),
        store_plex_metrics.get_all_metrics(
            start_date, end_date, instance_ids_parsed, user_ids_parsed
        ),
    )
    data = _merge_metrics(emby_data, jellyfin_data, plex_data)
    data["app_timezone"] = brein_config.TIMEZONE
    await brein_cache.set_media_metrics_cached(cache_key, data)
    return data


@router.get("/api/dashboard/media-drill")
async def api_dashboard_media_drill(
    current_user: CurrentUser,
    drill_type: str = Query(...),
    id: str = Query(...),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    instance_ids: str | None = Query(None),
    user_ids: str | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
):
    """Drill-down play sessions across Emby + Jellyfin + Plex.

    Capped per backend, newest first — the caller decides how deep, since the
    modal totals what it receives.
    """
    start_date, end_date = _parse_date_range(start_date, end_date)
    instance_ids_parsed = _parse_instance_ids(instance_ids)
    user_ids_parsed = _parse_user_ids(user_ids)

    if drill_type not in ("user", "series", "movie", "hour", "weekday", "media_type"):
        raise HTTPException(
            status_code=400,
            detail=(
                "drill_type must be user, series, movie, hour, weekday or media_type."
            ),
        )

    if drill_type == "user":
        # The id may carry its instance ("3:12345"). Without that scope the
        # bare id is matched by every backend and every instance, so drilling
        # Emby user 1 also returned the Plex account whose id is 1.
        user_instance: int | list[int] | None = instance_ids_parsed
        user_key = id
        if ":" in id:
            prefix, user_key = id.split(":", 1)
            try:
                user_instance = int(prefix)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="id must be 'instance_id:user_id'."
                )
        emby_rows, jellyfin_rows, plex_rows = await asyncio.gather(
            store_emby_metrics.get_user_sessions(
                start_date, end_date, user_key, user_instance, limit=limit
            ),
            store_jellyfin_metrics.get_user_sessions(
                start_date, end_date, user_key, user_instance, limit=limit
            ),
            store_plex_metrics.get_user_sessions(
                start_date, end_date, user_key, user_instance, limit=limit
            ),
        )
    elif drill_type == "media_type":
        emby_rows, jellyfin_rows, plex_rows = await asyncio.gather(
            store_emby_metrics.get_media_type_sessions(
                start_date,
                end_date,
                id,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
            store_jellyfin_metrics.get_media_type_sessions(
                start_date,
                end_date,
                id,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
            store_plex_metrics.get_media_type_sessions(
                start_date,
                end_date,
                id,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
        )
    elif drill_type in ("series", "movie"):
        emby_rows, jellyfin_rows, plex_rows = await asyncio.gather(
            store_emby_metrics.get_item_sessions(
                start_date,
                end_date,
                id,
                drill_type,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
            store_jellyfin_metrics.get_item_sessions(
                start_date,
                end_date,
                id,
                drill_type,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
            store_plex_metrics.get_item_sessions(
                start_date,
                end_date,
                id,
                drill_type,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
        )
    else:
        try:
            period_value = int(id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="id must be an integer for hour/weekday drill."
            )
        emby_rows, jellyfin_rows, plex_rows = await asyncio.gather(
            store_emby_metrics.get_time_sessions(
                start_date,
                end_date,
                drill_type,
                period_value,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
            store_jellyfin_metrics.get_time_sessions(
                start_date,
                end_date,
                drill_type,
                period_value,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
            store_plex_metrics.get_time_sessions(
                start_date,
                end_date,
                drill_type,
                period_value,
                instance_ids_parsed,
                limit=limit,
                user_ids=user_ids_parsed,
            ),
        )

    return sorted(
        _tag_backend(emby_rows, "emby")
        + _tag_backend(jellyfin_rows, "jellyfin")
        + _tag_backend(plex_rows, "plex"),
        key=lambda r: r.get("played_at") or "",
        reverse=False,
    )


@router.get("/api/dashboard/user-sessions")
async def api_dashboard_user_sessions(
    current_user: CurrentUser,
    user_id: str = Query(..., description="instance_id:user_id compound key"),
    date: str = Query(..., description="YYYY-MM-DD"),
    instance_ids: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Detailed watch sessions for a single user on a single day.

    All three backends, not just Emby: the Daily chart this feeds is built
    from merged rows, so a Jellyfin or Plex user's bar returned nothing.
    """
    # Validated like every sibling endpoint: an unparseable date used to
    # return an empty list, which reads as "nothing was watched".
    date, _ = _parse_date_range(date, date)
    instance_ids_parsed = _parse_instance_ids(instance_ids)
    emby_rows, jellyfin_rows, plex_rows = await asyncio.gather(
        store_emby_metrics.get_all_sessions(
            date, date, instance_id=instance_ids_parsed, user_ids=[user_id], limit=500
        ),
        store_jellyfin_metrics.get_all_sessions(
            date, date, instance_id=instance_ids_parsed, user_ids=[user_id], limit=500
        ),
        store_plex_metrics.get_all_sessions(
            date, date, instance_id=instance_ids_parsed, user_ids=[user_id], limit=500
        ),
    )
    return sorted(
        emby_rows + jellyfin_rows + plex_rows,
        key=lambda r: r.get("played_at") or "",
    )
