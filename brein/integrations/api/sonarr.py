"""Sonarr API client."""

from urllib.parse import urlencode

from .base import (
    delete_with_api_key,
    get_bytes_with_api_key,
    get_json_list_with_api_key,
    get_json_with_api_key,
    get_with_api_key,
    post_with_api_key,
    put_json_with_api_key,
)


async def download_backup(
    base_url: str, api_key: str, backup_id: int
) -> tuple[bool, bytes | None, str]:
    """Download backup file by ID. Returns (ok, content, filename_or_error)."""
    ok, data = await get_json_with_api_key(base_url, "/api/v3/system/backup", api_key)
    if not ok or not isinstance(data, list):
        return False, None, "Failed to fetch backup list"
    entry = next((b for b in data if b.get("id") == backup_id), None)
    if entry is None:
        return False, None, "Backup not found"
    name = entry.get("name", "")
    file_path = entry.get("path", "")
    ok2, content, msg = await get_bytes_with_api_key(base_url, file_path, api_key)
    if not ok2:
        return False, None, msg
    return True, content, name


async def test_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """Test connection to Sonarr (GET /api/v3/system/status). Returns (success, message)."""
    return await get_with_api_key(base_url, "/api/v3/system/status", api_key)


async def get_system_info(base_url: str, api_key: str) -> tuple[bool, dict | None]:
    """GET /api/v3/system/status (about/version info). Returns (True, data) or (False, None)."""
    return await get_json_with_api_key(base_url, "/api/v3/system/status", api_key)


async def ping(base_url: str, api_key: str) -> tuple[bool, str]:
    """Reachability check. *arr does not expose /api/v3/ping; use system/status like test_connection."""
    return await test_connection(base_url, api_key)


async def get_health(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """GET /api/v3/health."""
    return await get_json_list_with_api_key(base_url, "/api/v3/health", api_key)


async def get_config_host(base_url: str, api_key: str) -> tuple[bool, dict | None]:
    """GET /api/v3/config/host."""
    return await get_json_with_api_key(base_url, "/api/v3/config/host", api_key)


async def put_config_host(base_url: str, api_key: str, body: dict) -> tuple[bool, str]:
    """PUT /api/v3/config/host with full host config object."""
    return await put_json_with_api_key(
        base_url, "/api/v3/config/host", api_key, json_body=body
    )


async def get_series(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """GET /api/v3/series. Returns (True, list of series) or (False, None). Each series has totalEpisodeCount."""
    ok, data = await get_json_with_api_key(base_url, "/api/v3/series", api_key)
    if not ok or data is None:
        return False, None
    return True, data if isinstance(data, list) else []


async def get_series_by_id(
    base_url: str, api_key: str, series_id: int | str
) -> tuple[bool, dict | None]:
    """GET /api/v3/series/{id}. Returns (True, data) or (False, None)."""
    return await get_json_with_api_key(base_url, f"/api/v3/series/{series_id}", api_key)


# Sonarr defaults to pageSize=10, and the queue view presents what it is
# given as the whole queue — so a 25-item queue silently showed 10.
QUEUE_PAGE_SIZE = 200


async def get_queue(base_url: str, api_key: str) -> tuple[bool, dict | None]:
    """GET /api/v3/queue?includeEpisode=true. Returns (True, data) or (False, None)."""
    return await get_json_with_api_key(
        base_url,
        f"/api/v3/queue?includeEpisode=true&pageSize={QUEUE_PAGE_SIZE}",
        api_key,
    )


async def get_queue_details(
    base_url: str, api_key: str, queue_item_id: int | str
) -> tuple[bool, dict | None]:
    """GET /api/v3/queue/details?queueItemId=... Returns (True, data) or (False, None)."""
    path = "/api/v3/queue/details?" + urlencode({"queueItemId": queue_item_id})
    return await get_json_with_api_key(base_url, path, api_key)


_SONARR_EVENT_TYPE = {
    "grabbed": 1,
    "downloadFolderImported": 3,
    "downloadFailed": 4,
    "episodeFileDeleted": 5,
    "episodeFileRenamed": 6,
    "downloadIgnored": 7,
}


async def get_history(
    base_url: str,
    api_key: str,
    page: int = 1,
    page_size: int = 20,
    event_type: str = "",
    start_date: str = "",
    end_date: str = "",
) -> tuple[bool, dict | None]:
    """GET /api/v3/history with optional pagination and filters. Returns (True, data) or (False, None)."""
    params: dict[str, str | int] = {
        "page": page,
        "pageSize": page_size,
        "includeEpisode": "true",
    }
    if event_type and event_type in _SONARR_EVENT_TYPE:
        params["eventType"] = _SONARR_EVENT_TYPE[event_type]
    if start_date:
        params["startDate"] = (
            start_date if "T" in start_date else f"{start_date}T00:00:00Z"
        )
    if end_date:
        params["endDate"] = end_date if "T" in end_date else f"{end_date}T23:59:59Z"
    path = "/api/v3/history?" + urlencode(params)
    return await get_json_with_api_key(base_url, path, api_key)


async def get_history_series(
    base_url: str, api_key: str, series_id: int | str
) -> tuple[bool, dict | None]:
    """GET /api/v3/history/series?seriesId=... Returns (True, data) or (False, None)."""
    path = "/api/v3/history/series?" + urlencode({"seriesId": series_id})
    return await get_json_with_api_key(base_url, path, api_key)


async def get_calendar(
    base_url: str,
    api_key: str,
    start: str,
    end: str,
    unmonitored: bool = False,
) -> tuple[bool, list | None]:
    """GET /api/v3/calendar for date range. Returns (True, list of episode objects) or (False, None)."""
    path = "/api/v3/calendar?" + urlencode(
        {
            "start": start,
            "end": end,
            "unmonitored": str(unmonitored).lower(),
            "includeSeries": "true",
        }
    )
    ok, data = await get_json_with_api_key(base_url, path, api_key)
    if not ok or not isinstance(data, list):
        return False, None
    return True, data


async def get_wanted_missing(
    base_url: str,
    api_key: str,
    page: int = 1,
    page_size: int = 10,
    sort_key: str = "airDateUtc",
    sort_dir: str = "descending",
) -> tuple[bool, dict | None]:
    """GET /api/v3/wanted/missing with pagination. Returns (True, data) or (False, None)."""
    path = "/api/v3/wanted/missing?" + urlencode(
        {
            "page": page,
            "pageSize": page_size,
            "sortKey": sort_key,
            "sortDirection": sort_dir,
            "includeSeries": "true",
        }
    )
    return await get_json_with_api_key(base_url, path, api_key)


async def get_wanted_cutoff(
    base_url: str,
    api_key: str,
    page: int = 1,
    page_size: int = 10,
    sort_key: str = "airDateUtc",
    sort_dir: str = "descending",
) -> tuple[bool, dict | None]:
    """GET /api/v3/wanted/cutoff with pagination. Returns (True, data) or (False, None)."""
    path = "/api/v3/wanted/cutoff?" + urlencode(
        {
            "page": page,
            "pageSize": page_size,
            "sortKey": sort_key,
            "sortDirection": sort_dir,
            "includeSeries": "true",
        }
    )
    return await get_json_with_api_key(base_url, path, api_key)


async def get_log_entries(
    base_url: str,
    api_key: str,
    page: int = 1,
    page_size: int = 50,
    level: str = "",
) -> tuple[bool, dict | None]:
    """GET /api/v3/log with optional level filter. Returns (True, data) or (False, None)."""
    params: dict[str, str | int] = {
        "page": page,
        "pageSize": page_size,
        "sortKey": "time",
        "sortDirection": "descending",
    }
    if level:
        params["level"] = level
    return await get_json_with_api_key(
        base_url, "/api/v3/log?" + urlencode(params), api_key
    )


async def get_tasks(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """GET /api/v3/system/task. Returns (True, list) or (False, None)."""
    ok, data = await get_json_with_api_key(base_url, "/api/v3/system/task", api_key)
    if not ok or data is None:
        return False, None
    return True, data if isinstance(data, list) else []


async def get_backups(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """GET /api/v3/system/backup. Returns (True, list) or (False, None)."""
    ok, data = await get_json_with_api_key(base_url, "/api/v3/system/backup", api_key)
    if not ok or data is None:
        return False, None
    return True, data if isinstance(data, list) else []


async def delete_backup(
    base_url: str, api_key: str, backup_id: int
) -> tuple[bool, str]:
    """DELETE /api/v3/system/backup/{id}. Returns (success, message)."""
    return await delete_with_api_key(
        base_url, f"/api/v3/system/backup/{backup_id}", api_key
    )


async def post_command(base_url: str, api_key: str, body: dict) -> tuple[bool, str]:
    """POST /api/v3/command. Returns (success, message)."""
    return await post_with_api_key(base_url, "/api/v3/command", api_key, json_body=body)


async def get_log_file(base_url: str, api_key: str) -> tuple[bool, dict | list | None]:
    """GET /api/v2/log/file. Returns (True, data) or (False, None). Data may be list of files or log content."""
    return await get_json_with_api_key(base_url, "/api/v2/log/file", api_key)


async def get_blocklist(
    base_url: str,
    api_key: str,
    page: int = 1,
    page_size: int = 50,
) -> tuple[bool, dict | None]:
    """GET /api/v3/blocklist with pagination. Returns (True, data) or (False, None)."""
    path = "/api/v3/blocklist?" + urlencode({"page": page, "pageSize": page_size})
    return await get_json_with_api_key(base_url, path, api_key)


async def delete_queue_bulk(
    base_url: str,
    api_key: str,
    ids: list[int],
    remove_from_client: bool = True,
    blocklist: bool = False,
) -> tuple[bool, str]:
    """DELETE /api/v3/queue/bulk. Returns (success, message)."""
    path = "/api/v3/queue/bulk?" + urlencode(
        {
            "removeFromClient": str(remove_from_client).lower(),
            "blocklist": str(blocklist).lower(),
        }
    )
    return await delete_with_api_key(base_url, path, api_key, json_body={"ids": ids})


async def delete_blocklist_bulk(
    base_url: str,
    api_key: str,
    ids: list[int],
) -> tuple[bool, str]:
    """DELETE /api/v3/blocklist/bulk. Returns (success, message)."""
    return await delete_with_api_key(
        base_url, "/api/v3/blocklist/bulk", api_key, json_body={"ids": ids}
    )


async def post_system_backup(base_url: str, api_key: str) -> tuple[bool, str]:
    """POST /api/v3/system/backup. Returns (success, message)."""
    return await post_with_api_key(base_url, "/api/v3/system/backup", api_key)


async def post_system_restart(base_url: str, api_key: str) -> tuple[bool, str]:
    """POST /api/v3/system/restart. Returns (success, message)."""
    return await post_with_api_key(base_url, "/api/v3/system/restart", api_key)
