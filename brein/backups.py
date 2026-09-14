"""Database backup files.

Extracted from the Jinja handlers so the JSON API and the old HTML fragment
share one implementation rather than two copies of the same directory scan.
"""

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

import anyio.to_thread
from sqlalchemy import text as sa_text

from brein import config as brein_config
from brein import db as brein_db

log = logging.getLogger(__name__)

BACKUP_SUFFIXES = (".json", ".gz")


def backup_dir() -> Path:
    return Path(brein_config.BACKUP_DIR)


def _scan() -> list[dict[str, Any]]:
    directory = backup_dir()
    if not directory.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for entry in sorted(directory.iterdir(), reverse=True):
        if not (entry.is_file() and entry.suffix in BACKUP_SUFFIXES):
            continue
        try:
            stat = entry.stat()
        except OSError:
            # Removed between listing and stat.
            continue
        found.append(
            {"name": entry.name, "size": stat.st_size, "modified": stat.st_mtime}
        )
    return found


async def list_backups() -> list[dict[str, Any]]:
    """List backup files, newest first. Sizes are raw bytes, not pre-formatted."""
    return await anyio.to_thread.run_sync(_scan)


def resolve(filename: str) -> Path | None:
    """Resolve a backup filename to a path, refusing traversal."""
    safe_name = Path(filename).name
    path = backup_dir() / safe_name
    if path.suffix not in BACKUP_SUFFIXES or not path.is_file():
        return None
    return path


async def create_backup() -> str:
    """Dump every table to a timestamped JSON file. Returns the filename."""
    async with brein_db.get_session_factory()() as session:
        result = await session.execute(
            sa_text(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                " ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result.fetchall()]

    dump: dict[str, Any] = {}
    async with brein_db.get_session_factory()() as session:
        for table in tables:
            rows = await session.execute(sa_text(f'SELECT * FROM "{table}"'))
            cols = list(rows.keys())
            dump[table] = [
                {c: (str(v) if v is not None else None) for c, v in zip(cols, row)}
                for row in rows.fetchall()
            ]

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir() / f"backup_{timestamp}.json"

    def _write() -> None:
        # Serializing and writing a whole-database dump on the event loop would
        # stall every other request for its duration.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dump, indent=2), encoding="utf-8")
        # The dump holds API keys and password hashes verbatim, so keep it
        # readable only by the owning user.
        os.chmod(target, 0o600)

    await anyio.to_thread.run_sync(_write)
    return target.name
