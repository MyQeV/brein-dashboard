"""In-process cache with TTL.

All public functions are async to match the previous Redis-backed interface.
Cache is process-local and resets on restart — suitable for single-container deployments.
"""

import json
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 600
_EMBY_METRICS_TTL = 60

# Upper bound on everything held here. Poster images are cached as base64, so
# without a cap the process grows until the hourly sweep happens to run.
MAX_CACHE_BYTES = 64 * 1024 * 1024

# {key: (value_json, expires_at_monotonic)}
_store: dict[str, tuple[str, float]] = {}


def _current_bytes() -> int:
    return sum(len(v) for v, _ in _store.values())


def _get(key: str) -> Any:
    entry = _store.get(key)
    if entry is None:
        return None
    value_json, expires_at = entry
    if time.monotonic() > expires_at:
        _store.pop(key, None)
        return None
    return json.loads(value_json)


def _set(key: str, value: Any, ttl_seconds: int) -> None:
    _store[key] = (json.dumps(value, default=str), time.monotonic() + ttl_seconds)
    _enforce_size_limit()


def _enforce_size_limit() -> None:
    """Keep the cache under MAX_CACHE_BYTES.

    Expired entries go first; if that is not enough, the entries closest to
    expiry are dropped. Evicting from a cache only costs a recomputation, so
    dropping live entries is preferable to unbounded growth.
    """
    if _current_bytes() <= MAX_CACHE_BYTES:
        return
    sweep_expired()
    total = _current_bytes()
    if total <= MAX_CACHE_BYTES:
        return
    for key in sorted(_store, key=lambda k: _store[k][1]):
        value_json, _ = _store.pop(key)
        total -= len(value_json)
        if total <= MAX_CACHE_BYTES:
            break
    log.info("Cache over %d bytes; evicted down to %d", MAX_CACHE_BYTES, total)


async def get_cached(key: str) -> Any:
    """Return cached value for key, or None if missing or expired."""
    result = _get(f"cache:{key}")
    if result is None:
        log.debug("Cache miss %s", key)
    else:
        log.debug("Cache hit %s", key)
    return result


async def set_cached(
    key: str, value: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> None:
    """Store value with TTL."""
    _set(f"cache:{key}", value, ttl_seconds)
    log.debug("Cache set %s (ttl=%ds)", key, ttl_seconds)


def sweep_expired() -> int:
    """Remove all expired entries from the cache. Returns count deleted."""
    now = time.monotonic()
    keys = [k for k, (_, exp) in list(_store.items()) if now > exp]
    for k in keys:
        _store.pop(k, None)
    if keys:
        log.debug("Cache sweep: removed %d expired entries", len(keys))
    return len(keys)


async def get_media_metrics_cached(key: str) -> Any:
    """Return cached media-metrics (merged) payload for key, or None if missing."""
    return _get(f"media_metrics:{key}")


async def set_media_metrics_cached(key: str, value: Any) -> None:
    """Store a merged media-metrics payload."""
    _set(f"media_metrics:{key}", value, _EMBY_METRICS_TTL)


async def get_insight_cached(key: str) -> Any:
    """Return a cached insight payload (concurrency, unwatched) or None.

    These run window sorts and anti-joins over every session and library row,
    and the dashboard asks for them on each page load — the same TTL the
    metrics use is plenty.
    """
    return _get(f"insight:{key}")


async def set_insight_cached(key: str, value: Any) -> None:
    _set(f"insight:{key}", value, _EMBY_METRICS_TTL)


async def clear_media_metrics_cache() -> None:
    """Invalidate all merged media-metrics cache entries."""
    to_delete = [k for k in _store if k.startswith("media_metrics:")]
    for k in to_delete:
        _store.pop(k, None)
    log.debug("Media-metrics cache cleared (%d entries deleted)", len(to_delete))
