"""Settings API: system settings and logs (admin only)."""

import os
import re
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from brein import logging_setup as _logging_setup
from brein.web import auth as web_auth
from brein.web.schemas import User

router = APIRouter(prefix="/api/settings", tags=["settings"])
CurrentUser = Annotated[User, Depends(web_auth.get_current_admin_user)]
CurrentUserCookieOrBearer = Annotated[
    User, Depends(web_auth.get_current_admin_user_cookie_or_bearer)
]


@router.get("/system")
async def api_settings_system(_user: CurrentUser) -> list[dict]:
    """Return all system settings with current values (admin only)."""
    from brein.db import get_session_factory
    from brein.store import system_settings as store_system_settings

    factory = get_session_factory()
    async with factory() as session:
        return await store_system_settings.get_settings_with_values(session)


# ---------------------------------------------------------------------------
# Log viewer endpoints
# ---------------------------------------------------------------------------

# Built from the configured name rather than hard-coded: with
# BREIN_LOG_FILE=app.log — which logging_setup honours — every request to view
# or list a log was rejected as an invalid filename.
_LOG_FILENAME_RE = re.compile(
    rf"^{re.escape(_logging_setup.get_log_file())}(\.\d{{4}}-\d{{2}}-\d{{2}})?$"
)

_REDACT_PATTERNS = [
    (
        re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
        "Authorization: Bearer [REDACTED]",
    ),
    (re.compile(r"password=[^&\s]+", re.IGNORECASE), "password=[REDACTED]"),
    (re.compile(r"token=[^&\s]+", re.IGNORECASE), "token=[REDACTED]"),
    # SABnzbd and the *arr APIs pass their key in the query string.
    (re.compile(r"apikey=[^&\s]+", re.IGNORECASE), "apikey=[REDACTED]"),
    (re.compile(r"api_key=[^&\s]+", re.IGNORECASE), "api_key=[REDACTED]"),
]


def _safe_log_path(filename: str | None) -> str:
    """Resolve a log filename to an absolute path safely."""
    log_dir = _logging_setup.get_log_dir()
    name: str = filename if filename else _logging_setup.get_log_file()
    if not _LOG_FILENAME_RE.match(name):
        raise ValueError(f"Invalid log filename: {name!r}")
    candidate = os.path.realpath(os.path.join(log_dir, name))
    real_dir = os.path.realpath(log_dir)
    if not candidate.startswith(real_dir + os.sep) and candidate != real_dir:
        raise ValueError("Path traversal detected")
    return candidate


def _redact(line: str) -> str:
    for pattern, replacement in _REDACT_PATTERNS:
        line = pattern.sub(replacement, line)
    return line


@router.put("/system")
async def api_settings_system_save(_user: CurrentUser, body: dict[str, str]) -> dict:
    """Persist system settings (admin only).

    Returns the accepted values alongside any per-field errors rather than
    failing the whole request: one bad field should not discard the rest of
    the form.
    """
    from brein.db import get_session_factory
    from brein.store import system_settings as store_system_settings

    async with get_session_factory()() as session:
        errors = await store_system_settings.save_settings(session, body)
        settings = await store_system_settings.get_settings_with_values(session)
    return {"ok": not errors, "errors": errors, "settings": settings}


@router.get("/logs/files")
async def list_log_files(_user: CurrentUserCookieOrBearer) -> dict:
    """List available log files (admin only)."""
    log_dir = _logging_setup.get_log_dir()

    def _scan() -> list[dict[str, str | int | float]]:
        if not os.path.isdir(log_dir):
            return []
        found: list[dict[str, str | int | float]] = []
        for name in os.listdir(log_dir):
            if not _LOG_FILENAME_RE.match(name):
                continue
            try:
                stat = os.stat(os.path.join(log_dir, name))
            except OSError:
                # Rotated away between listdir and stat.
                continue
            found.append(
                {"name": name, "size": stat.st_size, "modified": stat.st_mtime}
            )
        found.sort(key=lambda f: float(f["modified"]), reverse=True)
        return found

    return {"files": await anyio.to_thread.run_sync(_scan)}


@router.get("/logs/view")
async def view_log(
    _user: CurrentUserCookieOrBearer,
    file: str | None = None,
    lines: int = Query(200, ge=1, le=500),
    level: str | None = None,
    search: str | None = None,
) -> dict:
    """Return last N lines of a log file, with optional level/search filter (admin only)."""
    try:
        path = _safe_log_path(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not os.path.isfile(path):
        return {"lines": [], "file": file or _logging_setup.get_log_file()}
    level_up = level.upper() if level else None

    def _read_matching_tail() -> list[str] | None:
        """Collect the last `lines` matching entries. Returns None on OSError."""
        collected: list[str] = []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
        except OSError:
            return None
        for raw in reversed(all_lines):
            stripped = raw.rstrip()
            if level_up and level_up not in stripped.upper():
                continue
            if search and search.lower() not in stripped.lower():
                continue
            collected.append(_redact(stripped))
            if len(collected) >= lines:
                break
        collected.reverse()
        return collected

    # Off the event loop: a day's log file can be large, and reading it here
    # would stall every other request for the duration of the read.
    result = await anyio.to_thread.run_sync(_read_matching_tail)
    if result is None:
        return {"lines": [], "file": file or _logging_setup.get_log_file()}
    return {"lines": result, "file": file or _logging_setup.get_log_file()}


@router.get("/logs/download")
async def download_log(
    _user: CurrentUserCookieOrBearer,
    file: str | None = None,
    level: str | None = None,
    search: str | None = None,
) -> StreamingResponse:
    """Download a log file as plain text, with optional filtering (admin only)."""
    try:
        path = _safe_log_path(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Log file not found")
    filename = os.path.basename(path)
    level_up = level.upper() if level else None

    def _iter():
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                stripped = raw.rstrip()
                if level_up and level_up not in stripped.upper():
                    continue
                if search and search.lower() not in stripped.lower():
                    continue
                yield _redact(stripped) + "\n"

    return StreamingResponse(
        _iter(),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
