"""Sonarr instance API (queue, history, missing, log, system)."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from brein import cache as brein_cache
from brein.integrations import sonarr as sonarr_integration
from brein.web import auth as web_auth
from brein.web.dependencies import require_instance_config
from brein.web.schemas import User

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]
WebUser = Annotated[User, Depends(web_auth.get_current_user_cookie_or_bearer)]
WebAdmin = Annotated[User, Depends(web_auth.get_current_admin_user_cookie_or_bearer)]

_SONARR_SORT_KEYS = frozenset(
    {
        "airDateUtc",
        "series.title",
        "episode",
        "status",
        "added",
        "absoluteEpisodeNumber",
        "episodeFileId",
    }
)
_SORT_DIRS = frozenset({"ascending", "descending"})

SONARR_ALLOWED_COMMANDS = frozenset(
    {
        "ApplicationUpdateCheck",
        "Backup",
        "CheckHealth",
        "CleanUpRecycleBin",
        "ClearBlocklist",
        "ClearLogs",
        "DeleteLogFiles",
        "DownloadedEpisodesScan",
        "EpisodeSearch",
        "Housekeeping",
        "ImportListSync",
        "MessagingCleanup",
        "MissingEpisodeSearch",
        "RefreshAndProcessMonitoredDownloads",
        "RefreshMonitoredDownloads",
        "RefreshSeries",
        "RenameFiles",
        "RenameSeries",
        "RescanSeries",
        "RssSync",
        "SeasonSearch",
        "SeriesSearch",
    }
)


class CommandRequest(BaseModel):
    """Validated Sonarr command body — name must be a known command."""

    name: str = Field(min_length=1, max_length=100)

    model_config = {"populate_by_name": True, "extra": "allow"}


SONARR_SERIES_CACHE_TTL = 300
SONARR_SERIES_CACHE_PREFIX = "sonarr_series:v2:"

SONARR_HOST_CONFIG_KEYS = frozenset(
    {
        "instanceName",
        "applicationUrl",
        "host",
        "port",
        "urlBase",
        "enableSsl",
        "sslPort",
    }
)


class SonarrHostConfigPatch(BaseModel):
    instanceName: str | None = None
    applicationUrl: str | None = None
    host: str | None = None
    port: int | None = None
    urlBase: str | None = None
    enableSsl: bool | None = None
    sslPort: int | None = None


async def _get_sonarr_config(instance_id: int) -> tuple[str, str]:
    """Resolve instance config; return (base_url, api_key) for Sonarr or raise."""
    _, base_url, api_key = await require_instance_config(
        instance_id, "sonarr", detail="Not a Sonarr instance"
    )
    return base_url, api_key


async def _enrich_sonarr_records_with_series(
    instance_id: int,
    base_url: str,
    api_key: str,
    records: list,
    series_id_key: str = "seriesId",
    fallback_id_key: str | None = None,
) -> None:
    """Attach series {title, year} to each record. Modifies records in place."""

    def _sid(r: dict):
        v = r.get(series_id_key)
        if v is not None:
            return v
        if fallback_id_key:
            return r.get(fallback_id_key)
        return None

    unique_ids = list({_sid(r) for r in records if _sid(r) is not None})
    if not unique_ids:
        for r in records:
            r["series"] = {}
        return
    series_map = {}
    uncached_ids = []
    for sid in unique_ids:
        cached = await brein_cache.get_cached(
            f"{SONARR_SERIES_CACHE_PREFIX}{instance_id}:{sid}",
        )
        if isinstance(cached, dict):
            series_map[sid] = cached
        else:
            uncached_ids.append(sid)
    if uncached_ids:
        series_results = await asyncio.gather(
            *[
                sonarr_integration.get_series_by_id(base_url, api_key, sid)
                for sid in uncached_ids
            ],
            return_exceptions=True,
        )
        for sid, result in zip(uncached_ids, series_results):
            if isinstance(result, BaseException) or result is None:
                series_map[sid] = {}
                continue
            ok_s, s = result
            if not ok_s or not isinstance(s, dict):
                series_map[sid] = {}
                continue
            entry = {"title": s.get("title"), "year": s.get("year")}
            series_map[sid] = entry
            await brein_cache.set_cached(
                f"{SONARR_SERIES_CACHE_PREFIX}{instance_id}:{sid}",
                entry,
                ttl_seconds=SONARR_SERIES_CACHE_TTL,
            )
    for r in records:
        r["series"] = series_map.get(_sid(r), {})


@router.get("/api/instances/{instance_id}/sonarr/queue")
async def api_instance_sonarr_queue(instance_id: int, current_user: CurrentUser):
    """Return Sonarr queue. 400 if not Sonarr. Enriched with series title and year."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_queue(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch queue")
    records = data.get("records") if isinstance(data, dict) else []
    if records:
        await _enrich_sonarr_records_with_series(
            instance_id, base_url, api_key, records, "seriesId"
        )
    return data


@router.get("/api/instances/{instance_id}/sonarr/queue/details")
async def api_instance_sonarr_queue_details(
    instance_id: int, current_user: CurrentUser, queueItemId: int = Query(...)
):
    """Return Sonarr queue item details. 400 if not Sonarr."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_queue_details(
        base_url, api_key, queueItemId
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch queue details")
    return data


@router.get("/api/instances/{instance_id}/sonarr/history")
async def api_instance_sonarr_history(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    eventType: str = Query(""),
    dateFrom: str = Query(""),
    dateTo: str = Query(""),
):
    """Return Sonarr history with optional pagination and filters. 400 if not Sonarr. Enriched with series title and year."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_history(
        base_url,
        api_key,
        page=page,
        page_size=pageSize,
        event_type=eventType,
        start_date=dateFrom,
        end_date=dateTo,
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch history")
    records = data.get("records") if isinstance(data, dict) else []
    if records:
        await _enrich_sonarr_records_with_series(
            instance_id, base_url, api_key, records, "seriesId"
        )
    return data


@router.get("/api/instances/{instance_id}/sonarr/history/series")
async def api_instance_sonarr_history_series(
    instance_id: int, current_user: CurrentUser, seriesId: int = Query(...)
):
    """Return Sonarr history for a series. 400 if not Sonarr."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_history_series(base_url, api_key, seriesId)
    if not ok or data is None:
        raise HTTPException(
            status_code=502, detail="Failed to fetch history for series"
        )
    return data


@router.get("/api/instances/{instance_id}/sonarr/wanted/missing")
async def api_instance_sonarr_wanted_missing(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=250),
    sortKey: str = Query("airDateUtc"),
    sortDir: str = Query("descending"),
):
    """Return Sonarr wanted/missing with pagination. Series embedded via includeSeries=true."""
    if sortKey not in _SONARR_SORT_KEYS:
        raise HTTPException(status_code=400, detail="Invalid sortKey")
    if sortDir not in _SORT_DIRS:
        raise HTTPException(status_code=400, detail="Invalid sortDir")
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_wanted_missing(
        base_url,
        api_key,
        page=page,
        page_size=pageSize,
        sort_key=sortKey,
        sort_dir=sortDir,
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch wanted/missing")
    return data


@router.get("/api/instances/{instance_id}/sonarr/wanted/cutoff")
async def api_instance_sonarr_wanted_cutoff(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=250),
    sortKey: str = Query("airDateUtc"),
    sortDir: str = Query("descending"),
):
    """Return Sonarr wanted/cutoff unmet with pagination."""
    if sortKey not in _SONARR_SORT_KEYS:
        raise HTTPException(status_code=400, detail="Invalid sortKey")
    if sortDir not in _SORT_DIRS:
        raise HTTPException(status_code=400, detail="Invalid sortDir")
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_wanted_cutoff(
        base_url,
        api_key,
        page=page,
        page_size=pageSize,
        sort_key=sortKey,
        sort_dir=sortDir,
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch wanted/cutoff")
    return data


@router.get("/api/instances/{instance_id}/sonarr/events")
async def api_instance_sonarr_events(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=250),
    level: str = Query(""),
):
    """Return Sonarr log entries (system events)."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_log_entries(
        base_url, api_key, page=page, page_size=pageSize, level=level
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch log entries")
    return data


@router.get("/api/instances/{instance_id}/sonarr/system/tasks")
async def api_instance_sonarr_system_tasks(instance_id: int, current_user: CurrentUser):
    """Return Sonarr scheduled tasks."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_tasks(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch tasks")
    return data


@router.get("/api/instances/{instance_id}/sonarr/system/backups")
async def api_instance_sonarr_system_backups(
    instance_id: int, current_user: CurrentUser
):
    """Return Sonarr backup list."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_backups(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch backups")
    return data


@router.delete("/api/instances/{instance_id}/sonarr/system/backups/{backup_id}")
async def api_instance_sonarr_delete_backup(
    instance_id: int, backup_id: int, current_user: AdminUser
):
    """Delete a Sonarr backup by ID. Admin only."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, msg = await sonarr_integration.delete_backup(base_url, api_key, backup_id)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Delete failed")
    return {"ok": True}


@router.get("/api/instances/{instance_id}/sonarr/system/backups/{backup_id}/download")
async def api_instance_sonarr_download_backup(
    instance_id: int, backup_id: int, current_user: AdminUser
):
    """Proxy-download a Sonarr backup file by ID.

    Admin only: the backup carries Sonarr's config database, including its API
    key and download-client credentials. Deleting one already required admin.
    """
    from fastapi.responses import Response as _FileResponse

    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, content, name_or_err = await sonarr_integration.download_backup(
        base_url, api_key, backup_id
    )
    if not ok or content is None:
        raise HTTPException(status_code=502, detail=name_or_err or "Download failed")
    return _FileResponse(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name_or_err}"'},
    )


@router.post("/api/instances/{instance_id}/sonarr/command")
async def api_instance_sonarr_command(
    instance_id: int,
    current_user: AdminUser,
    body: CommandRequest = Body(...),
):
    """Trigger a Sonarr command (e.g. MissingEpisodeSearch, EpisodeSearch). Admin only."""
    if body.name not in SONARR_ALLOWED_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unknown command: {body.name}")
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, msg = await sonarr_integration.post_command(
        base_url, api_key, body.model_dump(by_alias=False)
    )
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Command failed")
    return {"ok": True}


@router.delete("/api/instances/{instance_id}/sonarr/queue/bulk")
async def api_instance_sonarr_queue_delete_bulk(
    instance_id: int,
    current_user: AdminUser,
    ids: list[int] = Body(..., embed=True),
    removeFromClient: bool = Body(True),
    blocklist: bool = Body(False),
):
    """Delete Sonarr queue items in bulk. Admin only."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, msg = await sonarr_integration.delete_queue_bulk(
        base_url, api_key, ids, remove_from_client=removeFromClient, blocklist=blocklist
    )
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Delete failed")
    return {"ok": True}


@router.get("/api/instances/{instance_id}/sonarr/blocklist")
async def api_instance_sonarr_blocklist(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
):
    """Return Sonarr blocklist. 400 if not Sonarr. Enriched with series title and year."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_blocklist(
        base_url, api_key, page=page, page_size=pageSize
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch blocklist")
    records = data.get("records") if isinstance(data, dict) else []
    if records:
        await _enrich_sonarr_records_with_series(
            instance_id, base_url, api_key, records, "seriesId"
        )
    return data


@router.delete("/api/instances/{instance_id}/sonarr/blocklist/bulk")
async def api_instance_sonarr_blocklist_delete_bulk(
    instance_id: int,
    current_user: AdminUser,
    ids: list[int] = Body(..., embed=True),
):
    """Delete Sonarr blocklist items in bulk. Admin only."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, msg = await sonarr_integration.delete_blocklist_bulk(base_url, api_key, ids)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Delete failed")
    return {"ok": True}


@router.get("/api/instances/{instance_id}/sonarr/log/file")
async def api_instance_sonarr_log_file(instance_id: int, current_user: CurrentUser):
    """Return Sonarr log file list or content. 400 if not Sonarr."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_log_file(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch log file")
    return data


@router.get("/api/instances/{instance_id}/sonarr/ping")
async def api_instance_sonarr_ping(instance_id: int, current_user: WebUser):
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, msg = await sonarr_integration.ping(base_url, api_key)
    return {"ok": ok, "message": msg}


@router.get("/api/instances/{instance_id}/sonarr/config/host")
async def api_instance_sonarr_config_host_get(
    instance_id: int,
    current_user: WebAdmin,
):
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, data = await sonarr_integration.get_config_host(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch host config")
    return data


@router.put("/api/instances/{instance_id}/sonarr/config/host")
async def api_instance_sonarr_config_host_put(
    instance_id: int,
    current_user: WebAdmin,
    body: SonarrHostConfigPatch,
):
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, current = await sonarr_integration.get_config_host(base_url, api_key)
    if not ok or not isinstance(current, dict):
        raise HTTPException(status_code=502, detail="Failed to load host config")
    patch = body.model_dump(exclude_none=True)
    for key in patch:
        if key not in SONARR_HOST_CONFIG_KEYS:
            raise HTTPException(status_code=400, detail=f"Field not allowed: {key}")
    merged = {**current, **patch}
    ok2, msg = await sonarr_integration.put_config_host(base_url, api_key, merged)
    if not ok2:
        raise HTTPException(status_code=502, detail=msg or "Update failed")
    return {"ok": True, "message": msg}


@router.post("/api/instances/{instance_id}/sonarr/system/backup")
async def api_instance_sonarr_system_backup(instance_id: int, current_user: AdminUser):
    """Trigger Sonarr backup. Admin only."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, msg = await sonarr_integration.post_system_backup(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Backup failed")
    return {"ok": True, "message": msg}


@router.post("/api/instances/{instance_id}/sonarr/system/restart")
async def api_instance_sonarr_system_restart(instance_id: int, current_user: WebAdmin):
    """Trigger Sonarr restart. Admin only."""
    base_url, api_key = await _get_sonarr_config(instance_id)
    ok, msg = await sonarr_integration.post_system_restart(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Restart failed")
    return {"ok": True, "message": msg}
