"""Database admin routes: table lookup and data browsing. Admin only."""

import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import text

from brein import backups
from brein import db as brein_db
from brein.web import auth as web_auth
from brein.web.schemas import User

router = APIRouter(prefix="/api/database", tags=["database"])
log = logging.getLogger(__name__)

CurrentUser = Annotated[User, Depends(web_auth.get_current_admin_user)]

VALID_PER_PAGE = (10, 25, 50, 100)

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Columns never returned verbatim by the table browser. It is a viewer, not a
# credential store: an admin reading a table should not be handed every
# instance's API key or a password hash to take away offline. Backups still
# contain the real values — they have to round-trip to be worth anything.
SECRET_COLUMNS = frozenset(
    {"api_key", "hashed_password", "password", "refresh_token", "token_hash"}
)
REDACTED = "••• redacted"


def _validate_identifier(value: str, label: str) -> None:
    """Raise 400 if value does not match a safe PostgreSQL identifier pattern."""
    if not _SAFE_IDENTIFIER_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")


async def _get_tables() -> list[str]:
    """Return list of user table names from information_schema (excludes system tables)."""
    async with brein_db.get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                " ORDER BY table_name"
            )
        )
        return [row[0] for row in result.fetchall()]


def _group_tables_for_admin(table_names: list[str]) -> list[dict[str, Any]]:
    """Partition table names into labeled groups for the admin table browser UI."""
    remaining = set(table_names)
    groups: list[dict[str, Any]] = []

    def take(label: str, names: frozenset[str]) -> None:
        nonlocal remaining
        found = sorted(names & remaining)
        if found:
            groups.append({"label": label, "tables": found})
            remaining -= set(found)

    take(
        "Core & auth",
        frozenset({"users", "refresh_tokens", "token_blacklist", "user_preferences"}),
    )
    take(
        "App & configuration",
        frozenset({"app_instances", "service_config", "system_settings"}),
    )

    emby = sorted(t for t in remaining if t.startswith("emby_"))
    if emby:
        groups.append({"label": "Emby", "tables": emby})
        remaining -= set(emby)

    jellyfin = sorted(t for t in remaining if t.startswith("jellyfin_"))
    if jellyfin:
        groups.append({"label": "Jellyfin", "tables": jellyfin})
        remaining -= set(jellyfin)

    plex = sorted(t for t in remaining if t.startswith("plex_"))
    if plex:
        groups.append({"label": "Plex", "tables": plex})
        remaining -= set(plex)

    if remaining:
        groups.append({"label": "Other", "tables": sorted(remaining)})

    return groups


async def _get_columns(table_name: str) -> list[str]:
    """Return column names for a table from information_schema."""
    async with brein_db.get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = :table_name"
                " ORDER BY ordinal_position"
            ),
            {"table_name": table_name},
        )
        return [row[0] for row in result.fetchall()]


@router.get("/tables")
async def list_tables(_user: CurrentUser) -> dict:
    """List all user tables. Admin only."""
    tables = await _get_tables()
    return {"tables": tables, "groups": _group_tables_for_admin(tables)}


@router.get("/tables/{table_name}/rows")
async def get_table_rows(
    table_name: str,
    _user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
) -> dict:
    """Get paginated rows for a table. Admin only. sort_dir: asc or desc."""
    tables = await _get_tables()
    if table_name not in tables:
        raise HTTPException(status_code=404, detail="Table not found")

    if per_page not in VALID_PER_PAGE:
        per_page = 25
    if sort_dir.lower() not in ("asc", "desc"):
        sort_dir = "asc"

    columns = await _get_columns(table_name)
    if not columns:
        return {"rows": [], "columns": [], "total": 0}

    order_col = columns[0]
    if sort_by and sort_by in columns:
        order_col = sort_by

    # Belt-and-suspenders: validate identifier format independently of whitelist
    _validate_identifier(table_name, "table name")
    _validate_identifier(order_col, "column name")
    # direction is a hardcoded enum literal — not user input
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    async with brein_db.get_session_factory()() as session:
        count_result = await session.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        )
        total = count_result.scalar() or 0
        offset = (page - 1) * per_page
        rows_result = await session.execute(
            text(
                f'SELECT * FROM "{table_name}"'
                f' ORDER BY "{order_col}" {direction}'
                f" LIMIT :limit OFFSET :offset"
            ),
            {"limit": per_page, "offset": offset},
        )
        raw_rows = rows_result.mappings().fetchall()

    rows = []
    for row in raw_rows:
        d: dict[str, int | float | str | None] = {}
        for k, v in dict(row).items():
            if k.lower() in SECRET_COLUMNS:
                d[k] = None if v is None else REDACTED
            elif v is None:
                d[k] = None
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                d[k] = v
            else:
                d[k] = str(v)
        rows.append(d)
    return {"rows": rows, "columns": columns, "total": total}


@router.get("/backups")
async def list_backups_api(_user: CurrentUser) -> dict:
    """List database backups (admin only). Sizes are raw bytes."""
    return {"backups": await backups.list_backups()}


@router.post("/backups", status_code=201)
async def create_backup_api(_user: CurrentUser) -> dict:
    """Create a database backup (admin only)."""
    try:
        filename = await backups.create_backup()
    except Exception:
        log.exception("Backup failed")
        raise HTTPException(
            status_code=500,
            detail="Backup failed. Check the server logs for details.",
        ) from None
    return {"ok": True, "filename": filename}


@router.get("/backups/{filename}")
async def download_backup_api(filename: str, _user: CurrentUser) -> FileResponse:
    """Download a backup by name (admin only)."""
    path = backups.resolve(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(str(path), filename=path.name)


@router.post("/emby/reset-sessions", status_code=204)
async def reset_emby_sessions(_user: CurrentUser) -> None:
    """Delete all Emby playback sessions and session state. Admin only."""
    from brein.store import emby_playback_sessions as store_playback_sessions

    await store_playback_sessions.reset_all_sessions()
