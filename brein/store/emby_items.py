"""Emby item metadata store. Bulk-synced from /Items?IncludeItemTypes=... per type."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory

log = logging.getLogger(__name__)

NAME_MAX_LEN = 512

# Only rows whose metadata actually changed are written: the hourly sync
# re-sends the whole library, and rewriting every row bumped updated_at on
# all of them — so it said when the library was last walked, not when the
# item last changed — and left a full table's worth of dead tuples an hour.
_UPSERT_IF_CHANGED = (
    " WHERE (emby_items.type, emby_items.name, emby_items.server_id,"
    "  emby_items.series_id, emby_items.season_id, emby_items.parent_id,"
    "  emby_items.run_time_ticks, emby_items.index_number,"
    "  emby_items.parent_index_number)"
    " IS DISTINCT FROM"
    " (EXCLUDED.type, EXCLUDED.name, EXCLUDED.server_id, EXCLUDED.series_id,"
    "  EXCLUDED.season_id, EXCLUDED.parent_id, EXCLUDED.run_time_ticks,"
    "  EXCLUDED.index_number, EXCLUDED.parent_index_number)"
)


async def upsert_item(
    instance_id: int,
    item_id: str,
    item_type: str | None,
    name: str | None,
    server_id: str | None = None,
    series_id: str | None = None,
    season_id: str | None = None,
    parent_id: str | None = None,
    run_time_ticks: int | None = None,
    index_number: int | None = None,
    parent_index_number: int | None = None,
) -> None:
    """Insert or replace one row in emby_items."""
    if not item_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    name_val = (name or "")[:NAME_MAX_LEN] if name else None
    type_val = (item_type or "")[:64] if item_type else None
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO emby_items"
                " (instance_id, item_id, type, name, server_id, series_id, season_id,"
                "  parent_id, run_time_ticks, index_number, parent_index_number, updated_at)"
                " VALUES (:instance_id, :item_id, :type, :name, :server_id, :series_id,"
                "  :season_id, :parent_id, :run_time_ticks, :index_number,"
                "  :parent_index_number, :updated_at)"
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
                "  updated_at = EXCLUDED.updated_at" + _UPSERT_IF_CHANGED
            ),
            {
                "instance_id": instance_id,
                "item_id": item_id,
                "type": type_val,
                "name": name_val,
                "server_id": server_id,
                "series_id": series_id,
                "season_id": season_id,
                "parent_id": parent_id,
                "run_time_ticks": run_time_ticks,
                "index_number": index_number,
                "parent_index_number": parent_index_number,
                "updated_at": now,
            },
        )
        await session.commit()


async def upsert_items_bulk(
    instance_id: int,
    items: list[dict[str, Any]],
) -> int:
    """Bulk upsert a list of Emby item dicts into emby_items. Returns count of rows upserted."""
    if not items:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for item in items:
        item_id = item.get("Id")
        if item_id is None:
            continue
        item_id_str = str(item_id).strip()
        if not item_id_str:
            continue
        name_raw = item.get("Name")
        name_val = (name_raw or "")[:NAME_MAX_LEN] if name_raw else None
        type_raw = item.get("Type")
        type_val = (type_raw or "")[:64] if type_raw else None
        rows.append(
            {
                "instance_id": instance_id,
                "item_id": item_id_str,
                "type": type_val,
                "name": name_val,
                "server_id": item.get("ServerId"),
                "series_id": item.get("SeriesId"),
                "season_id": item.get("SeasonId"),
                "parent_id": item.get("ParentId"),
                "run_time_ticks": item.get("RunTimeTicks"),
                "index_number": item.get("IndexNumber"),
                "parent_index_number": item.get("ParentIndexNumber"),
                "updated_at": now,
            }
        )
    if not rows:
        return 0
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO emby_items"
                " (instance_id, item_id, type, name, server_id, series_id, season_id,"
                "  parent_id, run_time_ticks, index_number, parent_index_number, updated_at)"
                " VALUES (:instance_id, :item_id, :type, :name, :server_id, :series_id,"
                "  :season_id, :parent_id, :run_time_ticks, :index_number,"
                "  :parent_index_number, :updated_at)"
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
                "  updated_at = EXCLUDED.updated_at" + _UPSERT_IF_CHANGED
            ),
            rows,
        )
        await session.commit()
        return len(rows)


async def get_items(
    instance_id: int,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return emby_items for an instance, ordered by name ASC."""
    query = (
        "SELECT instance_id, item_id, type, name, server_id, series_id, season_id,"
        " parent_id, run_time_ticks, index_number, parent_index_number, updated_at"
        " FROM emby_items WHERE instance_id = :instance_id"
        " ORDER BY name ASC"
    )
    params: dict[str, Any] = {"instance_id": instance_id}
    if limit is not None and limit > 0:
        query += " LIMIT :limit"
        params["limit"] = limit
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        return [dict(r) for r in result.mappings().fetchall()]


async def get_last_scan_date(instance_id: int) -> str | None:
    """Return last_scan_date from emby_items_state for this instance, or None if not set."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT last_scan_date FROM emby_items_state WHERE instance_id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = result.fetchone()
        if row and row[0] is not None:
            return str(row[0])
        return None


async def set_last_scan_date(instance_id: int, last_scan_date: str) -> None:
    """Upsert last_scan_date for this instance into emby_items_state."""
    if not last_scan_date:
        return
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO emby_items_state (instance_id, last_scan_date)"
                " VALUES (:instance_id, :last_scan_date)"
                " ON CONFLICT (instance_id) DO UPDATE SET last_scan_date = EXCLUDED.last_scan_date"
            ),
            {"instance_id": instance_id, "last_scan_date": last_scan_date},
        )
        await session.commit()
