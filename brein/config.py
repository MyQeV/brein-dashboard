"""Load environment and app settings."""

import logging
import os
import zoneinfo
from datetime import date, datetime

_log = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        v = os.environ.get(name, "").strip()
        return int(v) if v else default
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        v = os.environ.get(name, "").strip()
        return float(v) if v else default
    except ValueError:
        return default


def _warn_if_no_secret() -> None:
    """Log warning when SECRET_KEY is missing (auth endpoints will fail)."""
    if not SECRET_KEY:
        _log.warning(
            "BREIN_SECRET_KEY / SECRET_KEY is not set; auth (login, JWT) will not work. "
            "Generate with: openssl rand -hex 32"
        )


def _warn_if_no_database_url() -> None:
    """Log warning when DATABASE_URL is missing."""
    if not DATABASE_URL:
        _log.warning(
            "DATABASE_URL is not set; database connections will fail. "
            "Example: postgresql+asyncpg://brein:password@localhost:5432/brein"  # pragma: allowlist secret
        )


# Load environment variables
DATABASE_URL: str = os.environ.get("DATABASE_URL", "").strip()

# Auth / JWT (from env; SECRET_KEY must be set in production)
SECRET_KEY: str = os.environ.get(
    "BREIN_SECRET_KEY", os.environ.get("SECRET_KEY", "")
).strip()
ALGORITHM: str = "HS256"
# Through _int_env like its siblings: a bare int() here raised at import time
# on a non-numeric value, which no operator ever sees as anything but a
# restart loop.
ACCESS_TOKEN_EXPIRE_MINUTES: int = _int_env("BREIN_ACCESS_TOKEN_EXPIRE_MINUTES", 30)
# Refresh token expiry: "Remember me" checked vs unchecked (in days)
REFRESH_TOKEN_EXPIRE_DAYS: int = _int_env("BREIN_REFRESH_TOKEN_EXPIRE_DAYS", 30)
REFRESH_TOKEN_EXPIRE_DAYS_SESSION: int = _int_env(
    "BREIN_REFRESH_TOKEN_EXPIRE_DAYS_SESSION", 7
)
FORCE_HTTPS: bool = os.environ.get("BREIN_FORCE_HTTPS", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Dev mode: uvicorn --reload in main.py, and the interactive API docs.
DEV: bool = os.environ.get("BREIN_DEV", "").strip().lower() in ("1", "true", "yes")
# Comma-separated IPs/CIDRs of trusted reverse proxies (e.g. "172.18.0.1" or "172.0.0.0/8").
# When set, rate limiting reads the real client IP from X-Forwarded-For instead of the proxy IP.
# Default empty = no proxy trust (uses TCP peer IP directly — safe default).
TRUSTED_PROXIES: list[str] = [
    v.strip()
    for v in os.environ.get("BREIN_TRUSTED_PROXIES", "").split(",")
    if v.strip()
]
# Whether to set the Secure flag on auth cookies.
# Defaults to FORCE_HTTPS; set BREIN_COOKIE_SECURE=true independently when TLS is
# terminated at a reverse proxy but FORCE_HTTPS is not enabled.
COOKIE_SECURE: bool = (
    os.environ.get("BREIN_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")
    if os.environ.get("BREIN_COOKIE_SECURE", "").strip()
    else FORCE_HTTPS
)

# Database pool settings
DB_POOL_SIZE: int = _int_env("BREIN_DB_POOL_SIZE", 10)
DB_MAX_OVERFLOW: int = _int_env("BREIN_DB_MAX_OVERFLOW", 20)

# Database backups. Must live under the mounted data volume (/app/data in
# docker-compose.yml) — anything else is wiped by the next image rebuild.
BACKUP_DIR: str = os.environ.get("BREIN_BACKUP_DIR", "").strip() or "/app/data/backups"

# Emby activity log sync (env: BREIN_EMBY_ACTIVITY_SYNC_*)
EMBY_ACTIVITY_SYNC_INTERVAL_SECONDS: int = _int_env(
    "BREIN_EMBY_ACTIVITY_SYNC_INTERVAL_SECONDS", 60
)
SNAPSHOT_REBUILD_INTERVAL_SECONDS: int = _int_env(
    "BREIN_SNAPSHOT_REBUILD_INTERVAL_SECONDS", 900
)
USERS_SYNC_INTERVAL_SECONDS: int = _int_env("BREIN_USERS_SYNC_INTERVAL_SECONDS", 60)
PLEX_USERS_SYNC_INTERVAL_SECONDS: int = _int_env(
    "BREIN_PLEX_USERS_SYNC_INTERVAL_SECONDS", 600
)
ITEMS_SYNC_INTERVAL_SECONDS: int = _int_env("BREIN_ITEMS_SYNC_INTERVAL_SECONDS", 3600)
SABNZBD_SERVER_STATS_INTERVAL_SECONDS: int = _int_env(
    "BREIN_SABNZBD_SERVER_STATS_INTERVAL_SECONDS", 3600
)

# Emby item cache: max items to fetch per sync run, batch size, delay between batches (env: BREIN_EMBY_ITEM_CACHE_*)
EMBY_ITEM_CACHE_MAX_PER_RUN: int = _int_env("BREIN_EMBY_ITEM_CACHE_MAX_PER_RUN", 200)
EMBY_ITEM_CACHE_BATCH_SIZE: int = _int_env("BREIN_EMBY_ITEM_CACHE_BATCH_SIZE", 50)
EMBY_ITEM_CACHE_BATCH_DELAY_SECONDS: float = _float_env(
    "BREIN_EMBY_ITEM_CACHE_BATCH_DELAY_SECONDS", 0.5
)


# Timezone for "today" calculations (dashboard default date range, etc.)
# Set via the standard TZ env var. Same value also drives PostgreSQL and
# container OS time, so app/database/log timestamps stay aligned.
# Must be a valid IANA timezone name (e.g. "Europe/Amsterdam", "America/New_York", "UTC").
def validate_timezone(value: str) -> bool:
    """Return True if value is a valid IANA timezone name, False otherwise."""
    try:
        zoneinfo.ZoneInfo(value)
        return True
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        return False


_RAW_TZ = os.environ.get("TZ", "UTC").strip() or "UTC"
# Validated here, not only where Python reads it: this value is also
# interpolated into `AT TIME ZONE :tz` in every metrics query, and Postgres
# raises on a name it does not know — so a typo'd TZ took the whole dashboard
# down with a 500 while `get_local_date()` quietly fell back to UTC.
TIMEZONE: str = _RAW_TZ if validate_timezone(_RAW_TZ) else "UTC"
if TIMEZONE != _RAW_TZ:
    _log.warning("Invalid TZ %r — using UTC.", _RAW_TZ)


def _resolve_tz() -> zoneinfo.ZoneInfo:
    """Return the configured ZoneInfo, falling back to UTC if invalid."""
    try:
        return zoneinfo.ZoneInfo(TIMEZONE)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        _log.warning("Invalid TZ %r — falling back to UTC.", TIMEZONE)
        return zoneinfo.ZoneInfo("UTC")


def get_local_date() -> date:
    """Return today's date in the configured TZ.

    Use this instead of date.today() so the dashboard date range matches
    the timezone of your Emby server.
    """
    return datetime.now(_resolve_tz()).date()


# Warnings
_warn_if_no_secret()
_warn_if_no_database_url()
