"""Radarr instance API (queue, history, missing, log, system)."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from brein import cache as brein_cache
from brein.integrations import radarr as radarr_integration
from brein.web import auth as web_auth
from brein.web.dependencies import require_instance_config
from brein.web.schemas import User

router = APIRouter()
CurrentUser = Annotated[User, Depends(web_auth.get_current_active_user)]
AdminUser = Annotated[User, Depends(web_auth.get_current_admin_user)]
WebUser = Annotated[User, Depends(web_auth.get_current_user_cookie_or_bearer)]
WebAdmin = Annotated[User, Depends(web_auth.get_current_admin_user_cookie_or_bearer)]

_RADARR_SORT_KEYS = frozenset(
    {
        "title",
        "sortTitle",
        "studio",
        "added",
        "year",
        "qualityProfileId",
        "movieFileId",
        "status",
        "inCinemas",
        "physicalRelease",
        "minimumAvailability",
    }
)
_SORT_DIRS = frozenset({"ascending", "descending"})

RADARR_ALLOWED_COMMANDS = frozenset(
    {
        "ApplicationCheckUpdate",
        "ApplicationUpdateCheck",
        "Backup",
        "CheckHealth",
        "CleanUpRecycleBin",
        "ClearBlocklist",
        "ClearLogs",
        "DeleteLogFiles",
        "DownloadedMoviesScan",
        "Housekeeping",
        "MessagingCleanup",
        "ImportListSync",
        "MissingMoviesSearch",
        "MoviesSearch",
        "RefreshAndProcessMonitoredDownloads",
        "RefreshMonitoredDownloads",
        "RefreshMovie",
        "RenameFiles",
        "RenameMovie",
        "RescanMovie",
        "RefreshCollections",
        "RssSync",
    }
)


class CommandRequest(BaseModel):
    """Validated Radarr command body — name must be a known command."""

    name: str = Field(min_length=1, max_length=100, alias="name")

    model_config = {"populate_by_name": True, "extra": "allow"}


RADARR_MOVIE_CACHE_TTL = 300
RADARR_MOVIE_CACHE_PREFIX = "radarr_movie:v2:"

RADARR_HOST_CONFIG_KEYS = frozenset(
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


class RadarrHostConfigPatch(BaseModel):
    instanceName: str | None = None
    applicationUrl: str | None = None
    host: str | None = None
    port: int | None = None
    urlBase: str | None = None
    enableSsl: bool | None = None
    sslPort: int | None = None


async def _get_radarr_config(instance_id: int) -> tuple[str, str]:
    """Resolve instance config; return (base_url, api_key) for Radarr or raise."""
    _, base_url, api_key = await require_instance_config(
        instance_id, "radarr", detail="Not a Radarr instance"
    )
    return base_url, api_key


async def _enrich_radarr_records_with_movie(
    instance_id: int,
    base_url: str,
    api_key: str,
    records: list,
    movie_id_key: str = "movieId",
) -> None:
    """Attach movie {title, year} to each record. Modifies records in place."""
    unique_ids = list(
        {r.get(movie_id_key) for r in records if r.get(movie_id_key) is not None}
    )
    if not unique_ids:
        for r in records:
            r["movie"] = {}
        return
    movie_map = {}
    uncached_ids = []
    for mid in unique_ids:
        cached = await brein_cache.get_cached(
            f"{RADARR_MOVIE_CACHE_PREFIX}{instance_id}:{mid}",
        )
        if isinstance(cached, dict):
            movie_map[mid] = cached
        else:
            uncached_ids.append(mid)
    if uncached_ids:
        movie_results = await asyncio.gather(
            *[
                radarr_integration.get_movie(base_url, api_key, mid)
                for mid in uncached_ids
            ],
            return_exceptions=True,
        )
        for mid, result in zip(uncached_ids, movie_results):
            if isinstance(result, BaseException) or result is None:
                movie_map[mid] = {}
                continue
            ok_m, m = result
            if not ok_m or not isinstance(m, dict):
                movie_map[mid] = {}
                continue
            entry = {"title": m.get("title"), "year": m.get("year")}
            movie_map[mid] = entry
            await brein_cache.set_cached(
                f"{RADARR_MOVIE_CACHE_PREFIX}{instance_id}:{mid}",
                entry,
                ttl_seconds=RADARR_MOVIE_CACHE_TTL,
            )
    for r in records:
        r["movie"] = movie_map.get(r.get(movie_id_key), {})


@router.get("/api/instances/{instance_id}/radarr/collection")
async def api_instance_radarr_collection(instance_id: int, current_user: CurrentUser):
    """Return Radarr collections with per-movie isExisting/isExcluded status."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_collections(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch collections")
    return data


@router.get("/api/instances/{instance_id}/radarr/queue")
async def api_instance_radarr_queue(instance_id: int, current_user: CurrentUser):
    """Return Radarr queue. 400 if not Radarr. Enriched with movie title and year."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_queue(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch queue")
    records = data.get("records") if isinstance(data, dict) else []
    if records:
        await _enrich_radarr_records_with_movie(
            instance_id, base_url, api_key, records, "movieId"
        )
    return data


@router.get("/api/instances/{instance_id}/radarr/history")
async def api_instance_radarr_history(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    eventType: str = Query(""),
    dateFrom: str = Query(""),
    dateTo: str = Query(""),
):
    """Return Radarr history with optional pagination and filters. 400 if not Radarr. Enriched with movie title and year."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_history(
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
    if not records:
        return data
    await _enrich_radarr_records_with_movie(
        instance_id, base_url, api_key, records, "movieId"
    )
    return data


@router.get("/api/instances/{instance_id}/radarr/history/movie")
async def api_instance_radarr_history_movie(
    instance_id: int, current_user: CurrentUser, movieId: int = Query(...)
):
    """Return Radarr history for a movie. 400 if not Radarr."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_history_movie(base_url, api_key, movieId)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch history for movie")
    return data


@router.get("/api/instances/{instance_id}/radarr/wanted/missing")
async def api_instance_radarr_wanted_missing(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=250),
    sortKey: str = Query("title"),
    sortDir: str = Query("ascending"),
):
    """Return Radarr wanted/missing with pagination."""
    if sortKey not in _RADARR_SORT_KEYS:
        raise HTTPException(status_code=400, detail="Invalid sortKey")
    if sortDir not in _SORT_DIRS:
        raise HTTPException(status_code=400, detail="Invalid sortDir")
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_wanted_missing(
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


@router.get("/api/instances/{instance_id}/radarr/wanted/cutoff")
async def api_instance_radarr_wanted_cutoff(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=250),
    sortKey: str = Query("title"),
    sortDir: str = Query("ascending"),
):
    """Return Radarr wanted/cutoff unmet with pagination."""
    if sortKey not in _RADARR_SORT_KEYS:
        raise HTTPException(status_code=400, detail="Invalid sortKey")
    if sortDir not in _SORT_DIRS:
        raise HTTPException(status_code=400, detail="Invalid sortDir")
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_wanted_cutoff(
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


@router.get("/api/instances/{instance_id}/radarr/events")
async def api_instance_radarr_events(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=250),
    level: str = Query(""),
):
    """Return Radarr log entries (system events)."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_log_entries(
        base_url, api_key, page=page, page_size=pageSize, level=level
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch log entries")
    return data


@router.get("/api/instances/{instance_id}/radarr/system/tasks")
async def api_instance_radarr_system_tasks(instance_id: int, current_user: CurrentUser):
    """Return Radarr scheduled tasks."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_tasks(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch tasks")
    return data


@router.get("/api/instances/{instance_id}/radarr/system/backups")
async def api_instance_radarr_system_backups(
    instance_id: int, current_user: CurrentUser
):
    """Return Radarr backup list."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_backups(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch backups")
    return data


@router.delete("/api/instances/{instance_id}/radarr/system/backups/{backup_id}")
async def api_instance_radarr_delete_backup(
    instance_id: int, backup_id: int, current_user: AdminUser
):
    """Delete a Radarr backup by ID. Admin only."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, msg = await radarr_integration.delete_backup(base_url, api_key, backup_id)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Delete failed")
    return {"ok": True}


@router.get("/api/instances/{instance_id}/radarr/system/backups/{backup_id}/download")
async def api_instance_radarr_download_backup(
    instance_id: int, backup_id: int, current_user: AdminUser
):
    """Proxy-download a Radarr backup file by ID.

    Admin only: the backup carries Radarr's config database, including its API
    key and download-client credentials. Deleting one already required admin.
    """
    from fastapi.responses import Response as _FileResponse

    base_url, api_key = await _get_radarr_config(instance_id)
    ok, content, name_or_err = await radarr_integration.download_backup(
        base_url, api_key, backup_id
    )
    if not ok or content is None:
        raise HTTPException(status_code=502, detail=name_or_err or "Download failed")
    return _FileResponse(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name_or_err}"'},
    )


@router.post("/api/instances/{instance_id}/radarr/command")
async def api_instance_radarr_command(
    instance_id: int,
    current_user: AdminUser,
    body: CommandRequest = Body(...),
):
    """Trigger a Radarr command (e.g. MissingMoviesSearch, MoviesSearch). Admin only."""
    if body.name not in RADARR_ALLOWED_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unknown command: {body.name}")
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, msg = await radarr_integration.post_command(
        base_url, api_key, body.model_dump(by_alias=False)
    )
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Command failed")
    return {"ok": True}


@router.delete("/api/instances/{instance_id}/radarr/queue/bulk")
async def api_instance_radarr_queue_delete_bulk(
    instance_id: int,
    current_user: AdminUser,
    ids: list[int] = Body(..., embed=True),
    removeFromClient: bool = Body(True),
    blocklist: bool = Body(False),
):
    """Delete Radarr queue items in bulk. Admin only."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, msg = await radarr_integration.delete_queue_bulk(
        base_url, api_key, ids, remove_from_client=removeFromClient, blocklist=blocklist
    )
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Delete failed")
    return {"ok": True}


@router.get("/api/instances/{instance_id}/radarr/blocklist")
async def api_instance_radarr_blocklist(
    instance_id: int,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
):
    """Return Radarr blocklist. 400 if not Radarr. Enriched with movie title and year."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_blocklist(
        base_url, api_key, page=page, page_size=pageSize
    )
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch blocklist")
    records = data.get("records") if isinstance(data, dict) else []
    if records:
        await _enrich_radarr_records_with_movie(
            instance_id, base_url, api_key, records, "movieId"
        )
    return data


@router.delete("/api/instances/{instance_id}/radarr/blocklist/bulk")
async def api_instance_radarr_blocklist_delete_bulk(
    instance_id: int,
    current_user: AdminUser,
    ids: list[int] = Body(..., embed=True),
):
    """Delete Radarr blocklist items in bulk. Admin only."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, msg = await radarr_integration.delete_blocklist_bulk(base_url, api_key, ids)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Delete failed")
    return {"ok": True}


@router.get("/api/instances/{instance_id}/radarr/log/file")
async def api_instance_radarr_log_file(instance_id: int, current_user: CurrentUser):
    """Return Radarr log file list or content. 400 if not Radarr."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_log_file(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch log file")
    return data


@router.get("/api/instances/{instance_id}/radarr/ping")
async def api_instance_radarr_ping(instance_id: int, current_user: WebUser):
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, msg = await radarr_integration.ping(base_url, api_key)
    return {"ok": ok, "message": msg}


@router.get("/api/instances/{instance_id}/radarr/config/host")
async def api_instance_radarr_config_host_get(
    instance_id: int,
    current_user: WebAdmin,
):
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, data = await radarr_integration.get_config_host(base_url, api_key)
    if not ok or data is None:
        raise HTTPException(status_code=502, detail="Failed to fetch host config")
    return data


@router.put("/api/instances/{instance_id}/radarr/config/host")
async def api_instance_radarr_config_host_put(
    instance_id: int,
    current_user: WebAdmin,
    body: RadarrHostConfigPatch,
):
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, current = await radarr_integration.get_config_host(base_url, api_key)
    if not ok or not isinstance(current, dict):
        raise HTTPException(status_code=502, detail="Failed to load host config")
    patch = body.model_dump(exclude_none=True)
    for key in patch:
        if key not in RADARR_HOST_CONFIG_KEYS:
            raise HTTPException(status_code=400, detail=f"Field not allowed: {key}")
    merged = {**current, **patch}
    ok2, msg = await radarr_integration.put_config_host(base_url, api_key, merged)
    if not ok2:
        raise HTTPException(status_code=502, detail=msg or "Update failed")
    return {"ok": True, "message": msg}


@router.post("/api/instances/{instance_id}/radarr/system/backup")
async def api_instance_radarr_system_backup(instance_id: int, current_user: AdminUser):
    """Trigger Radarr backup. Admin only."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, msg = await radarr_integration.post_system_backup(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Backup failed")
    return {"ok": True, "message": msg}


@router.post("/api/instances/{instance_id}/radarr/system/restart")
async def api_instance_radarr_system_restart(instance_id: int, current_user: WebAdmin):
    """Trigger Radarr restart. Admin only."""
    base_url, api_key = await _get_radarr_config(instance_id)
    ok, msg = await radarr_integration.post_system_restart(base_url, api_key)
    if not ok:
        raise HTTPException(status_code=502, detail=msg or "Restart failed")
    return {"ok": True, "message": msg}
