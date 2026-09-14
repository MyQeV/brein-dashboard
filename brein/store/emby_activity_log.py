"""Store for Emby activity log entries (System/ActivityLog/Entries) per instance."""

import logging
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory

log = logging.getLogger(__name__)

_BATCH_SIZE = 2000


def _row_dict_from_item(item: dict[str, Any], instance_id: int) -> dict[str, Any]:
    """Build a parameter dict for emby_activity_log_entries from an API item."""
    raw_item_id = item.get("ItemId")
    raw_user_id = item.get("UserId")
    try:
        item_id = (
            int(raw_item_id)
            if raw_item_id is not None and str(raw_item_id).strip() != ""
            else None
        )
    except (TypeError, ValueError):
        item_id = None
    try:
        user_id = (
            int(raw_user_id)
            if raw_user_id is not None and str(raw_user_id).strip() != ""
            else None
        )
    except (TypeError, ValueError):
        user_id = None
    return {
        "instance_id": instance_id,
        "entry_id": int(item.get("Id") or 0),
        "name": (item.get("Name") or "")[:4096] if item.get("Name") else None,
        "type": (item.get("Type") or "")[:256] if item.get("Type") else None,
        "item_id": item_id,
        "date": item.get("Date") or "",
        "user_id": user_id,
        "overview": (item.get("Overview") or "")[:8192]
        if item.get("Overview")
        else None,
    }


async def upsert_entries(instance_id: int, entries: list[dict[str, Any]]) -> None:
    """Batch upsert activity log entries for an instance."""
    if not entries:
        return
    async with get_session_factory()() as session:
        for i in range(0, len(entries), _BATCH_SIZE):
            batch = entries[i : i + _BATCH_SIZE]
            # An entry with no usable Id would key to (instance_id, 0), where
            # each such row overwrites the last and only one survives the batch.
            rows = [
                _row_dict_from_item(it, instance_id)
                for it in batch
                if str(it.get("Id") or "").strip()
            ]
            if not rows:
                continue
            await session.execute(
                text(
                    "INSERT INTO emby_activity_log_entries"
                    " (instance_id, entry_id, name, type, item_id, date, user_id, overview)"
                    " VALUES (:instance_id, :entry_id, :name, :type, :item_id, :date,"
                    "  :user_id, :overview)"
                    " ON CONFLICT (instance_id, entry_id) DO UPDATE SET"
                    "  name = EXCLUDED.name,"
                    "  type = EXCLUDED.type,"
                    "  item_id = EXCLUDED.item_id,"
                    "  date = EXCLUDED.date,"
                    "  user_id = EXCLUDED.user_id,"
                    "  overview = EXCLUDED.overview"
                ),
                rows,
            )
        await session.commit()


async def get_max_entry_id(instance_id: int) -> int | None:
    """Return MAX(entry_id) for this instance; None if no rows."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT MAX(entry_id) FROM emby_activity_log_entries WHERE instance_id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = result.fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return None


async def get_min_date_after_entry_id(instance_id: int, entry_id: int) -> str | None:
    """Return the smallest date for rows with entry_id > given value; None if none."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT MIN(date) FROM emby_activity_log_entries"
                " WHERE instance_id = :instance_id AND entry_id > :entry_id"
            ),
            {"instance_id": instance_id, "entry_id": entry_id},
        )
        row = result.fetchone()
        if row and row[0] is not None:
            return str(row[0])
        return None


async def get_max_date(instance_id: int) -> str | None:
    """Return MAX(date) for this instance; None if no rows."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT MAX(date) FROM emby_activity_log_entries WHERE instance_id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        row = result.fetchone()
        if row and row[0] is not None:
            return str(row[0])
        return None


async def get_entries(
    instance_id: int,
    min_date: str | None = None,
    max_date: str | None = None,
    user_id: int | None = None,
    type_filter: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return activity log entries for an instance, optionally filtered by date range, user, and type. Ordered by entry_id DESC."""
    query = (
        "SELECT instance_id, entry_id, name, type, item_id, date, user_id, overview"
        " FROM emby_activity_log_entries WHERE instance_id = :instance_id"
    )
    params: dict[str, Any] = {"instance_id": instance_id}
    if min_date:
        query += " AND date >= :min_date"
        params["min_date"] = min_date
    if max_date:
        query += " AND date <= :max_date"
        params["max_date"] = max_date
    if user_id is not None:
        query += " AND user_id = :user_id"
        params["user_id"] = user_id
    if type_filter:
        query += " AND type = :type_filter"
        params["type_filter"] = type_filter
    query += " ORDER BY entry_id DESC"
    if limit is not None and limit > 0:
        query += " LIMIT :limit"
        params["limit"] = limit
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        return [dict(r) for r in result.mappings().fetchall()]


async def get_distinct_types(instance_id: int) -> list[str]:
    """Return sorted list of distinct type values for this instance."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT DISTINCT type FROM emby_activity_log_entries"
                " WHERE instance_id = :instance_id AND type IS NOT NULL ORDER BY type"
            ),
            {"instance_id": instance_id},
        )
        return [row[0] for row in result.fetchall()]
