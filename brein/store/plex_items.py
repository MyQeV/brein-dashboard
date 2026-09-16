"""Plex library metadata store. Bulk-synced from /library/all per media type."""

from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory
from brein.integrations.api.plex import rating_key_from_plex_metadata_dict

NAME_MAX_LEN = 512

# Only rows whose metadata actually changed are written: the hourly sync
# re-sends the whole library, and rewriting every row bumped updated_at on
# all of them — so it said when the library was last walked, not when the
# item last changed — and left a full table's worth of dead tuples an hour.
_UPSERT_IF_CHANGED = (
    " WHERE (plex_items.type, plex_items.name, plex_items.server_id,"
    "  plex_items.series_id, plex_items.season_id, plex_items.parent_id,"
    "  plex_items.run_time_ticks, plex_items.index_number,"
    "  plex_items.parent_index_number, plex_items.library_section_id,"
    "  plex_items.guid)"
    " IS DISTINCT FROM"
    " (EXCLUDED.type, EXCLUDED.name, EXCLUDED.server_id, EXCLUDED.series_id,"
    "  EXCLUDED.season_id, EXCLUDED.parent_id, EXCLUDED.run_time_ticks,"
    "  EXCLUDED.index_number, EXCLUDED.parent_index_number,"
    "  EXCLUDED.library_section_id, EXCLUDED.guid)"
)


def _optional_str_id(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _optional_int_field(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _library_section_str(m: dict[str, Any]) -> str | None:
    v = m.get("librarySectionID")
    if v is None:
        return None
    return str(v).strip() or None


def row_from_plex_metadata(
    instance_id: int,
    m: dict[str, Any],
    server_id: str,
    updated_at: str,
) -> dict[str, Any] | None:
    """Map one Plex Metadata dict to a plex_items upsert row, or None if no rating key."""
    item_id = rating_key_from_plex_metadata_dict(m)
    if not item_id:
        return None
    duration_ms = m.get("duration")
    run_time_ticks: int | None = None
    if duration_ms is not None:
        try:
            run_time_ticks = int(duration_ms) * 10000
        except (TypeError, ValueError):
            run_time_ticks = None
    ptype = (m.get("type") or "").lower()
    parent_id = _optional_str_id(m.get("parentRatingKey"))
    gprk = _optional_str_id(m.get("grandparentRatingKey"))

    series_id: str | None = gprk
    season_id: str | None = None
    if ptype == "episode":
        series_id = gprk
        season_id = parent_id
    elif ptype == "season":
        series_id = parent_id
        season_id = item_id
    elif ptype == "show":
        series_id = item_id
        parent_id = None
    elif ptype == "movie":
        series_id = None
        season_id = None
        parent_id = None

    title_raw = m.get("title")
    name_val = (title_raw or "")[:NAME_MAX_LEN] if title_raw else None
    type_val = (m.get("type") or "")[:64] if m.get("type") else None
    guid_raw = m.get("guid")
    guid_val = str(guid_raw) if guid_raw is not None else None

    return {
        "instance_id": instance_id,
        "item_id": item_id,
        "type": type_val,
        "name": name_val,
        "server_id": server_id or None,
        "series_id": series_id,
        "season_id": season_id,
        "parent_id": parent_id,
        "run_time_ticks": run_time_ticks,
        "index_number": _optional_int_field(m.get("index")),
        "parent_index_number": _optional_int_field(m.get("parentIndex")),
        "updated_at": updated_at,
        "library_section_id": _library_section_str(m),
        "guid": guid_val,
    }


async def upsert_items_bulk(
    instance_id: int,
    rows: list[dict[str, Any]],
) -> int:
    """Bulk upsert rows into plex_items. Returns count of rows written."""
    if not rows:
        return 0
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO plex_items"
                " (instance_id, item_id, type, name, server_id, series_id, season_id,"
                "  parent_id, run_time_ticks, index_number, parent_index_number, updated_at,"
                "  library_section_id, guid)"
                " VALUES (:instance_id, :item_id, :type, :name, :server_id, :series_id,"
                "  :season_id, :parent_id, :run_time_ticks, :index_number,"
                "  :parent_index_number, :updated_at, :library_section_id, :guid)"
                " ON CONFLICT (instance_id, item_id) DO UPDATE SET"
                "  type = EXCLUDED.type,"
                "  name = EXCLUDED.name,"
                "  server_id = EXCLUDED.server_id,"
                "  series_id = EXCLUDED.series_id,"
                "  season_id = EXCLUDED.season_id,"
                "  parent_id = EXCLUDED.parent_id,"
                "  run_time_ticks = EXCLUDED.run_time_ticks,"
                "  index_number = EXCLUDED.index_number,"
                "  parent_index_number = EXCLUDED.parent_index_number,"
                "  updated_at = EXCLUDED.updated_at,"
                "  library_section_id = EXCLUDED.library_section_id,"
                "  guid = EXCLUDED.guid" + _UPSERT_IF_CHANGED
            ),
            rows,
        )
        await session.commit()
        return len(rows)


async def get_last_scan_date(instance_id: int) -> str | None:
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT last_scan_date FROM plex_items_state WHERE instance_id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = result.fetchone()
        if row and row[0] is not None:
            return str(row[0])
        return None


async def set_last_scan_date(instance_id: int, last_scan_date: str) -> None:
    if not last_scan_date:
        return
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO plex_items_state (instance_id, last_scan_date)"
                " VALUES (:instance_id, :last_scan_date)"
                " ON CONFLICT (instance_id) DO UPDATE SET last_scan_date = EXCLUDED.last_scan_date"
            ),
            {"instance_id": instance_id, "last_scan_date": last_scan_date},
        )
        await session.commit()
