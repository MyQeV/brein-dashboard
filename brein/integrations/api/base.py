"""Base HTTP client for external APIs."""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger(__name__)

DEFAULT_HTTP_TIMEOUT = 10.0

_shared_client: httpx.AsyncClient | None = None


class SsrfBlockedError(httpx.HTTPError):
    """Raised when a request targets a blocked (loopback/link-local) address."""


async def _ssrf_request_hook(request: httpx.Request) -> None:
    """Reject requests to blocked addresses, whatever built them.

    Registered on every client this module hands out. Checking here rather
    than at each call site means a new integration cannot forget the guard,
    and it covers redirects too — httpx runs request hooks per redirect hop.
    """
    if await _is_ssrf_risk_url(str(request.url)):
        # Origin only: the full URL carries the API key for the services
        # that take it as a query parameter, and this message ends up in
        # the log and in the connection-test reply.
        origin = f"{request.url.scheme}://{request.url.netloc.decode('ascii')}"
        raise SsrfBlockedError(f"Blocked request to restricted address: {origin}")


def new_http_client(timeout: float = DEFAULT_HTTP_TIMEOUT) -> httpx.AsyncClient:
    """Create a client with the SSRF guard attached.

    Use this instead of httpx.AsyncClient() anywhere in the integrations.
    """
    return httpx.AsyncClient(
        timeout=timeout, event_hooks={"request": [_ssrf_request_hook]}
    )


def get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it on first call."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = new_http_client()
    return _shared_client


async def close_http_client() -> None:
    """Close the shared httpx client (call on app shutdown)."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


# Restricted ranges: loopback, unspecified, link-local and cloud metadata only.
# LAN ranges (10.x, 172.16.x, 192.168.x) are allowed — users legitimately point to local media servers.
_BLOCKED_RANGES = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
]


async def _is_ssrf_risk_url(url: str) -> bool:
    """Return True if the URL resolves to a blocked (loopback/cloud-metadata) address.

    Resolution goes through ``loop.getaddrinfo`` rather than
    ``socket.gethostbyname``: the latter is a blocking syscall, and every
    outbound request in this package passes through here, so a slow or
    unreachable DNS server would stall the whole event loop for the resolver
    timeout.

    Every resolved address is checked, not just the first — a hostname with
    several A records must not slip through because one of them is public.
    An IPv4-mapped IPv6 address (``::ffff:127.0.0.1``) is checked as the
    IPv4 address it wraps, since it connects to the same place.

    This lookup is separate from the one httpx makes to connect, so a name
    whose record changes between the two (DNS rebinding) is not caught. The
    guard is a filter on the configured URL, not a guarantee about the
    socket that is eventually opened.
    """
    host = urlparse(url).hostname or ""
    if not host:
        return False
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except Exception:
        # Unresolvable host: let the request itself fail with a real error.
        return False

    for info in infos:
        sockaddr = info[4]
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if any(addr in net for net in _BLOCKED_RANGES):
            return True
    return False


def normalize_base_url(url: str) -> str:
    """Ensure base URL has no trailing slash."""
    return (url or "").strip().rstrip("/")


def redirect_message(r: httpx.Response) -> str:
    """What a connection test reports for a 3xx answer.

    The clients never follow redirects, so an http:// URL that a server
    answers with a 301 to https:// used to pass the test (301 < 400) and then
    fail every data call, which insists on 200. The query string is dropped
    from the Location: a server that echoes it back would put the API key in
    the message.
    """
    location = (r.headers.get("location") or "").split("?", 1)[0] or "another URL"
    return f"Server redirected to {location} — use that URL"


async def get_with_api_key(
    base_url: str,
    path: str,
    api_key: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> tuple[bool, str]:
    """
    GET base_url + path with X-Api-Key header.
    Returns (success, message or error string).
    """
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, "Invalid base URL"
    if await _is_ssrf_risk_url(base):
        return False, "Invalid base URL"
    url = urljoin(base + "/", path.lstrip("/"))
    headers = {"X-Api-Key": api_key} if api_key else {}
    try:
        client = get_http_client()
        r = await client.get(url, headers=headers, timeout=timeout)
        if 300 <= r.status_code < 400:
            return False, redirect_message(r)
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("Connection error to %s: %s", url, e)
        return False, f"Connection failed: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {e!s}"
    except Exception as e:
        log.exception("Request error")
        return False, str(e)


async def get_json_with_api_key(
    base_url: str,
    path: str,
    api_key: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> tuple[bool, dict | None]:
    """
    GET base_url + path with X-Api-Key header; parse JSON.
    Returns (True, data) on success, (False, None) on error.
    """
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, None
    if await _is_ssrf_risk_url(base):
        return False, None
    url = urljoin(base + "/", path.lstrip("/"))
    headers = {"X-Api-Key": api_key} if api_key else {}
    try:
        client = get_http_client()
        r = await client.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            log.warning(
                "get_json HTTP %s from %s%s",
                r.status_code,
                base,
                "/" + path.lstrip("/").split("?", 1)[0],
            )
            return False, None
        return True, r.json()
    except Exception as e:
        log.warning("get_json error %s: %s", url, e)
        return False, None


async def get_json_list_with_api_key(
    base_url: str,
    path: str,
    api_key: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> tuple[bool, list | None]:
    """GET with X-Api-Key; parse JSON array. Returns (True, list) or (False, None)."""
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, None
    if await _is_ssrf_risk_url(base):
        return False, None
    url = urljoin(base + "/", path.lstrip("/"))
    headers = {"X-Api-Key": api_key} if api_key else {}
    try:
        client = get_http_client()
        r = await client.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            log.warning(
                "get_json_list HTTP %s from %s%s",
                r.status_code,
                base,
                "/" + path.lstrip("/").split("?", 1)[0],
            )
            return False, None
        data = r.json()
        return (True, data) if isinstance(data, list) else (False, None)
    except Exception as e:
        log.warning("get_json_list error %s: %s", url, e)
        return False, None


async def get_bytes_with_api_key(
    base_url: str,
    path: str,
    api_key: str,
    timeout: float = 60.0,
) -> tuple[bool, bytes | None, str]:
    """
    GET base_url + path with X-Api-Key header; return raw bytes.
    Uses a fresh client with a longer timeout for file downloads.
    Returns (True, content, "OK") on success, (False, None, error) on failure.
    """
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, None, "Invalid base URL"
    if await _is_ssrf_risk_url(base):
        return False, None, "Invalid base URL"
    url = urljoin(base + "/", path.lstrip("/"))
    headers = {"X-Api-Key": api_key} if api_key else {}
    try:
        async with new_http_client(timeout) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 401:
            return False, None, "Invalid API key"
        if r.status_code >= 400:
            return False, None, f"HTTP {r.status_code}"
        return True, r.content, "OK"
    except Exception as e:
        log.warning("get_bytes error %s: %s", url, e)
        return False, None, str(e)


async def delete_with_api_key(
    base_url: str,
    path: str,
    api_key: str,
    json_body: dict | list | None = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> tuple[bool, str]:
    """
    DELETE base_url + path with X-Api-Key header; optional JSON body.
    Returns (success, message or error string).
    """
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, "Invalid base URL"
    if await _is_ssrf_risk_url(base):
        return False, "Invalid base URL"
    url = urljoin(base + "/", path.lstrip("/"))
    headers = {"X-Api-Key": api_key} if api_key else {}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    try:
        client = get_http_client()
        r = await client.request(
            "DELETE", url, headers=headers, json=json_body, timeout=timeout
        )
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("Connection error to %s: %s", url, e)
        return False, f"Connection failed: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {e!s}"
    except Exception as e:
        log.exception("Request error")
        return False, str(e)


async def put_json_with_api_key(
    base_url: str,
    path: str,
    api_key: str,
    json_body: dict | None = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> tuple[bool, str]:
    """
    PUT base_url + path with X-Api-Key header and JSON body.
    Returns (success, message or error string).
    """
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, "Invalid base URL"
    if await _is_ssrf_risk_url(base):
        return False, "Invalid base URL"
    url = urljoin(base + "/", path.lstrip("/"))
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    try:
        client = get_http_client()
        r = await client.put(url, headers=headers, json=json_body, timeout=timeout)
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("Connection error to %s: %s", url, e)
        return False, f"Connection failed: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {e!s}"
    except Exception as e:
        log.exception("Request error")
        return False, str(e)


async def post_with_api_key(
    base_url: str,
    path: str,
    api_key: str,
    json_body: dict | None = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> tuple[bool, str]:
    """
    POST base_url + path with X-Api-Key header; optional JSON body.
    Returns (success, message or error string).
    """
    base = normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        return False, "Invalid base URL"
    if await _is_ssrf_risk_url(base):
        return False, "Invalid base URL"
    url = urljoin(base + "/", path.lstrip("/"))
    headers = {"X-Api-Key": api_key} if api_key else {}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    try:
        client = get_http_client()
        r = await client.post(url, headers=headers, json=json_body, timeout=timeout)
        if r.status_code == 401:
            return False, "Invalid API key"
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "OK"
    except httpx.ConnectError as e:
        log.warning("Connection error to %s: %s", url, e)
        return False, f"Connection failed: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {e!s}"
    except Exception as e:
        log.exception("Request error")
        return False, str(e)


def parse_credentials(api_key: str) -> tuple[str, str] | None:
    """Split 'username:password' into (username, password). Returns None if no colon present."""
    if ":" not in api_key:
        return None
    username, _, password = api_key.partition(":")
    return username, password
