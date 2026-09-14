"""SABnzbd API client."""

import logging

import httpx

from .base import (
    DEFAULT_HTTP_TIMEOUT,
    _is_ssrf_risk_url,
    get_http_client,
    normalize_base_url,
)

log = logging.getLogger(__name__)


def _authenticated(response: httpx.Response) -> bool:
    """Whether SABnzbd actually answered, rather than refusing the key.

    A bad key is not an HTTP error: SABnzbd replies 200 with
    ``{"status": false, "error": "API Key Incorrect"}``. Read as success that
    became an empty queue and a 0 MB/s speed — indistinguishable from an idle
    downloader.
    """
    try:
        payload = response.json()
    except ValueError:
        return True
    if isinstance(payload, dict) and payload.get("status") is False:
        log.warning("SABnzbd refused the request: %s", payload.get("error"))
        return False
    return True


async def test_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """Test connection to SABnzbd (GET /api?mode=version&apikey=...).
    Returns (success, message).
    """
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, "Invalid base URL"
    if await _is_ssrf_risk_url(base):
        return False, "Invalid base URL"
    url = f"{base}/api"
    # `mode=version` is served without a key, so testing with it reported OK
    # for any key at all. `queue` is the cheapest mode that authenticates.
    params = {"mode": "queue", "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(url, params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("Connection error to %s: %s", url, e)
        return False, f"Connection failed: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {e!s}"
    except Exception as e:
        log.exception("Request error")
        return False, str(e)


async def get_queue(base_url: str, api_key: str) -> tuple[bool, dict | None]:
    """Fetch SABnzbd queue. Returns (True, queue_dict) or (False, None)."""
    base = normalize_base_url(base_url)
    params = {"mode": "queue", "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400 or not _authenticated(r):
            return False, None
        return True, r.json()
    except Exception:
        log.exception("SABnzbd get_queue error")
        return False, None


async def get_speed_limit_config(base_url: str, api_key: str) -> tuple[bool, int]:
    """Read configured speed limit percentage from SABnzbd config.
    Returns (True, pct) where pct is 1-100, or (False, 100) on error.
    0 from SABnzbd means unlimited — we return 100.
    """
    base = normalize_base_url(base_url)
    params = {
        "mode": "get_config",
        "section": "misc",
        "keyword": "speed_limit",
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400 or not _authenticated(r):
            return False, 100
        data = r.json()
        raw = int(
            float(data.get("config", {}).get("misc", {}).get("speed_limit", 0) or 0)
        )
        return True, raw or 100
    except Exception:
        log.exception("SABnzbd get_speed_limit_config error")
        return False, 100


async def pause_queue(base_url: str, api_key: str) -> tuple[bool, str]:
    """Pause SABnzbd queue. Returns (True, 'OK') or (False, error)."""
    base = normalize_base_url(base_url)
    params = {"mode": "pause", "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd pause_queue error")
        return False, str(e)


async def resume_queue(base_url: str, api_key: str) -> tuple[bool, str]:
    """Resume SABnzbd queue. Returns (True, 'OK') or (False, error)."""
    base = normalize_base_url(base_url)
    params = {"mode": "resume", "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd resume_queue error")
        return False, str(e)


async def set_speed_limit(base_url: str, api_key: str, value: int) -> tuple[bool, str]:
    """Set SABnzbd speed limit. value 1-100 = percentage; 0 = unlimited."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "config",
        "name": "speedlimit",
        "apikey": api_key,
        "value": value,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd set_speed_limit error")
        return False, str(e)


async def pause_timed(base_url: str, api_key: str, minutes: int) -> tuple[bool, str]:
    """Pause queue for N minutes (0 = indefinite)."""
    base = normalize_base_url(base_url)
    params = {"mode": "pause", "value": minutes, "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd pause_timed error")
        return False, str(e)


async def pause_nzo(base_url: str, api_key: str, nzo_id: str) -> tuple[bool, str]:
    """Pause a single queue item."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "queue",
        "name": "pause",
        "value": nzo_id,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd pause_nzo error")
        return False, str(e)


async def resume_nzo(base_url: str, api_key: str, nzo_id: str) -> tuple[bool, str]:
    """Resume a single queue item."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "queue",
        "name": "resume",
        "value": nzo_id,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd resume_nzo error")
        return False, str(e)


async def delete_nzo(base_url: str, api_key: str, nzo_id: str) -> tuple[bool, str]:
    """Delete a single queue item (also deletes partial files)."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "queue",
        "name": "delete",
        "value": nzo_id,
        "del_files": 1,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd delete_nzo error")
        return False, str(e)


async def move_nzo(
    base_url: str, api_key: str, nzo_id: str, new_index: int
) -> tuple[bool, str]:
    """Move a queue item to a new 0-based position."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "switch",
        "value": nzo_id,
        "value2": new_index,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        data = r.json()
        if not data.get("status", True):
            log.warning("SABnzbd move_nzo returned status=false: %s", data)
            return False, "SABnzbd rejected move"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd move_nzo error")
        return False, str(e)


async def sort_queue(
    base_url: str, api_key: str, field: str, direction: str
) -> tuple[bool, str]:
    """Sort queue. field: avg_age|name|size. direction: asc|desc."""
    valid_fields = {"avg_age", "name", "size"}
    valid_dirs = {"asc", "desc"}
    if field not in valid_fields or direction not in valid_dirs:
        return False, "Invalid sort parameters"
    base = normalize_base_url(base_url)
    params = {
        "mode": "queue",
        "name": "sort",
        "sort": field,
        "dir": direction,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd sort_queue error")
        return False, str(e)


async def get_history_filtered(
    base_url: str,
    api_key: str,
    failed_only: bool = False,
    limit: int | None = None,
    start: int | None = None,
) -> tuple[bool, list | None]:
    """Fetch SABnzbd history, optionally filtered to failed-only."""
    base = normalize_base_url(base_url)
    params: dict = {"mode": "history", "apikey": api_key, "output": "json"}
    if failed_only:
        params["failed_only"] = 1
    if limit is not None:
        params["limit"] = limit
    if start is not None:
        params["start"] = start
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400 or not _authenticated(r):
            return False, None
        return True, r.json().get("history", {}).get("slots", [])
    except Exception:
        log.exception("SABnzbd get_history_filtered error")
        return False, None


async def get_history_archived(base_url: str, api_key: str) -> tuple[bool, list | None]:
    """Fetch SABnzbd archived history items (archive=1)."""
    base = normalize_base_url(base_url)
    params: dict = {
        "mode": "history",
        "archive": 1,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400 or not _authenticated(r):
            return False, None
        return True, r.json().get("history", {}).get("slots", [])
    except Exception:
        log.exception("SABnzbd get_history_archived error")
        return False, None


async def retry_history(base_url: str, api_key: str, nzo_id: str) -> tuple[bool, str]:
    """Retry a single failed history item."""
    base = normalize_base_url(base_url)
    params = {"mode": "retry", "value": nzo_id, "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd retry_history error")
        return False, str(e)


async def retry_all_history(base_url: str, api_key: str) -> tuple[bool, str]:
    """Retry all failed history items."""
    base = normalize_base_url(base_url)
    params = {"mode": "retry_all", "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd retry_all_history error")
        return False, str(e)


async def delete_history(base_url: str, api_key: str, nzo_id: str) -> tuple[bool, str]:
    """Delete/archive a single history item."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "history",
        "name": "delete",
        "value": nzo_id,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd delete_history error")
        return False, str(e)


async def purge_history(base_url: str, api_key: str) -> tuple[bool, str]:
    """Purge entire history."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "history",
        "name": "delete",
        "value": "all",
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd purge_history error")
        return False, str(e)


async def mark_completed(base_url: str, api_key: str, nzo_id: str) -> tuple[bool, str]:
    """Mark a failed history item as completed."""
    base = normalize_base_url(base_url)
    params = {
        "mode": "history",
        "name": "mark_as_completed",
        "value": nzo_id,
        "apikey": api_key,
        "output": "json",
    }
    try:
        client = get_http_client()
        r = await client.get(f"{base}/api", params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if not _authenticated(r):
            return False, "Invalid API key"
        return True, "OK"
    except Exception as e:
        log.exception("SABnzbd mark_completed error")
        return False, str(e)


async def get_status(
    base_url: str,
    api_key: str,
    *,
    skip_dashboard: int = 1,
    calculate_performance: int = 0,
) -> tuple[bool, dict | None]:
    """GET api?mode=status. skip_dashboard=1 avoids slow public IP lookup."""
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, None
    if await _is_ssrf_risk_url(base):
        return False, None
    url = f"{base}/api"
    params = {
        "mode": "status",
        "apikey": api_key,
        "output": "json",
        "skip_dashboard": skip_dashboard,
        "calculate_performance": calculate_performance,
    }
    try:
        client = get_http_client()
        r = await client.get(url, params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code != 200 or not _authenticated(r):
            return False, None
        data = r.json()
        return (True, data) if isinstance(data, dict) else (False, None)
    except Exception as e:
        log.warning("SABnzbd get_status error: %s", e)
        return False, None


def parse_server_stats_bytes(
    payload: dict | None,
) -> tuple[int | None, int | None, int | None, int | None]:
    """Extract (today, week, month, total) byte totals from server_stats JSON."""
    if not payload or not isinstance(payload, dict):
        return None, None, None, None

    def _n(v: object) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v if v >= 0 else None
        if isinstance(v, float):
            return int(v) if v >= 0 else None
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        return None

    total = payload.get("total")
    if isinstance(total, dict):
        d, w, m, t = (
            _n(total.get("day")),
            _n(total.get("week")),
            _n(total.get("month")),
            _n(total.get("total")),
        )
        if any(x is not None for x in (d, w, m, t)):
            return d, w, m, t

    servers = payload.get("servers")
    if isinstance(servers, list):
        d_sum = w_sum = m_sum = t_sum = 0
        any_v = False
        for s in servers:
            if not isinstance(s, dict):
                continue
            block = s.get("total") if isinstance(s.get("total"), dict) else s
            if not isinstance(block, dict):
                continue
            dd = _n(block.get("day"))
            ww = _n(block.get("week"))
            mm = _n(block.get("month"))
            tt = _n(block.get("total"))
            if dd is not None:
                d_sum += dd
                any_v = True
            if ww is not None:
                w_sum += ww
                any_v = True
            if mm is not None:
                m_sum += mm
                any_v = True
            if tt is not None:
                t_sum += tt
                any_v = True
        if any_v:
            return (
                d_sum or None,
                w_sum or None,
                m_sum or None,
                t_sum or None,
            )

    return (
        _n(payload.get("day")),
        _n(payload.get("week")),
        _n(payload.get("month")),
        _n(payload.get("total")),
    )


def parse_server_stats_daily_timeline(payload: dict | None) -> dict[str, int]:
    """Sum per-calendar-day download bytes from ``server_stats`` JSON.

    SABnzbd exposes each server's ``daily`` map (``YYYY-MM-DD`` -> bytes). Keys are
    server-local calendar days. Missing dates are omitted (treated as zero when charting).
    """
    if not payload or not isinstance(payload, dict):
        return {}

    def _byte(v: object) -> int | None:
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v if v >= 0 else None
        if isinstance(v, float):
            return int(v) if v >= 0 else None
        return None

    out: dict[str, int] = {}
    servers = payload.get("servers")
    blocks: list[dict] = []
    if isinstance(servers, dict):
        for block in servers.values():
            if isinstance(block, dict):
                blocks.append(block)
    elif isinstance(servers, list):
        for s in servers:
            if isinstance(s, dict):
                blocks.append(s)

    for block in blocks:
        daily = block.get("daily")
        if not isinstance(daily, dict):
            continue
        for date_str, val in daily.items():
            if not isinstance(date_str, str) or len(date_str) < 10:
                continue
            b = _byte(val)
            if b is None:
                continue
            out[date_str] = out.get(date_str, 0) + b

    return out


async def get_server_stats(base_url: str, api_key: str) -> tuple[bool, dict | None]:
    """GET api?mode=server_stats."""
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, None
    if await _is_ssrf_risk_url(base):
        return False, None
    url = f"{base}/api"
    params = {"mode": "server_stats", "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(url, params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code != 200 or not _authenticated(r):
            return False, None
        data = r.json()
        return (True, data) if isinstance(data, dict) else (False, None)
    except Exception as e:
        log.warning("SABnzbd get_server_stats error: %s", e)
        return False, None


async def restart(base_url: str, api_key: str) -> tuple[bool, str]:
    """GET api?mode=restart."""
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, "Invalid base URL"
    if await _is_ssrf_risk_url(base):
        return False, "Invalid base URL"
    url = f"{base}/api"
    params = {"mode": "restart", "apikey": api_key, "output": "json"}
    try:
        client = get_http_client()
        r = await client.get(url, params=params, timeout=DEFAULT_HTTP_TIMEOUT)
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        try:
            data = r.json()
            if isinstance(data, dict) and data.get("status") is False:
                return False, str(data.get("error") or "Restart rejected")
        except Exception:
            # SABnzbd answers a restart with a non-JSON body on some versions;
            # the 2xx above is the real signal.
            log.debug("SABnzbd restart response was not JSON", exc_info=True)
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("SABnzbd restart connection error: %s", e)
        return False, f"Connection failed: {e!s}"
    except Exception as e:
        log.exception("SABnzbd restart error")
        return False, str(e)
