"""Plex playback sessions derived from live /status/sessions polling (finalize on session end)."""

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory
from brein.integrations.api.plex import rating_key_from_plex_session_dict

_MIN_WATCH_SECONDS = 30

# Earliest start_time finalised since the snapshot rebuild last asked, so it
# can re-aggregate only the days that can have changed. In-process state,
# like the rebuild throttle that reads it.
_snapshot_since_utc: str | None = None


def take_snapshot_since() -> str | None:
    """Hand over (and clear) the oldest start_time finalised since the last call."""
    global _snapshot_since_utc
    since, _snapshot_since_utc = _snapshot_since_utc, None
    return since


def _optional_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _optional_str(v: Any, max_len: int) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:max_len]


def _account_display_name(user: dict[str, Any]) -> str | None:
    """Plex session User display name (title / username / friendlyName)."""
    for key in ("title", "username", "friendlyName"):
        raw = user.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            return s[:512]
    return None


def _extract_trackable_session(
    s: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Return (plex_session_key, fields) or None if not trackable."""
    user = s.get("User")
    if not user or not isinstance(user, dict):
        return None
    session_sub = s.get("Session") or {}
    if not isinstance(session_sub, dict):
        session_sub = {}
    key = str(session_sub.get("id") or "").strip()
    if not key:
        return None
    aid = _optional_int(user.get("id"))
    rk = rating_key_from_plex_session_dict(s)
    vo = _optional_int(s.get("viewOffset")) or 0
    dur = _optional_int(s.get("duration")) or 0
    return key, {
        "account_id": aid,
        "account_title": _account_display_name(user),
        "rating_key": rk,
        "item_type": _optional_str(s.get("type"), 64),
        "title": _optional_str(s.get("title"), 4096),
        "grandparent_title": _optional_str(
            s.get("grandparentTitle") or s.get("grandparent_title"), 4096
        ),
        "parent_title": _optional_str(
            s.get("parentTitle") or s.get("parent_title"), 4096
        ),
        "view_offset_ms": max(0, vo),
        "duration_ms": max(0, dur),
    }


async def process_live_poll(instance_id: int, sessions: list[Any]) -> None:
    """Upsert active Plex sessions; finalize rows that disappeared from this poll."""
    global _snapshot_since_utc
    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()
    current_keys: set[str] = set()
    upserts: list[tuple[str, dict[str, Any]]] = []
    for raw in sessions:
        if not isinstance(raw, dict):
            continue
        got = _extract_trackable_session(raw)
        if not got:
            continue
        key, fields = got
        current_keys.add(key)
        upserts.append((key, fields))

    async with get_session_factory()() as session:
        for plex_session_key, f in upserts:
            await session.execute(
                text(
                    "INSERT INTO plex_playback_sessions_active ("
                    " instance_id, plex_session_key, account_id, account_title, rating_key,"
                    " item_type, title, grandparent_title, parent_title,"
                    " view_offset_ms, duration_ms, started_at_wall, last_seen_at_wall)"
                    " VALUES ("
                    " :instance_id, :plex_session_key, :account_id, :account_title, :rating_key,"
                    " :item_type, :title, :grandparent_title, :parent_title,"
                    " :view_offset_ms, :duration_ms, :started_at_wall, :last_seen_at_wall)"
                    " ON CONFLICT (instance_id, plex_session_key) DO UPDATE SET"
                    " account_id = EXCLUDED.account_id,"
                    " account_title = EXCLUDED.account_title,"
                    " rating_key = EXCLUDED.rating_key,"
                    " item_type = EXCLUDED.item_type,"
                    " title = EXCLUDED.title,"
                    " grandparent_title = EXCLUDED.grandparent_title,"
                    " parent_title = EXCLUDED.parent_title,"
                    " view_offset_ms = EXCLUDED.view_offset_ms,"
                    " duration_ms = EXCLUDED.duration_ms,"
                    " last_seen_at_wall = EXCLUDED.last_seen_at_wall"
                ),
                {
                    "instance_id": instance_id,
                    "plex_session_key": plex_session_key,
                    "account_id": f["account_id"],
                    "account_title": f["account_title"],
                    "rating_key": f["rating_key"],
                    "item_type": f["item_type"],
                    "title": f["title"],
                    "grandparent_title": f["grandparent_title"],
                    "parent_title": f["parent_title"],
                    "view_offset_ms": f["view_offset_ms"],
                    "duration_ms": f["duration_ms"],
                    "started_at_wall": now,
                    "last_seen_at_wall": now,
                },
            )

        res_prev = await session.execute(
            text(
                "SELECT instance_id, plex_session_key, account_id, account_title, rating_key,"
                " item_type, title, grandparent_title, parent_title,"
                " view_offset_ms, duration_ms, started_at_wall, last_seen_at_wall"
                " FROM plex_playback_sessions_active"
                " WHERE instance_id = :instance_id"
            ),
            {"instance_id": instance_id},
        )
        existing_rows = [dict(x) for x in res_prev.mappings().fetchall()]
        for row in existing_rows:
            pk = str(row["plex_session_key"])
            if pk in current_keys:
                continue
            started = float(row["started_at_wall"])
            start_iso = datetime.fromtimestamp(started, tz=timezone.utc).isoformat()
            vo = int(row["view_offset_ms"] or 0)
            dur = int(row["duration_ms"] or 0)
            # Known difference from Emby/Jellyfin, kept on purpose: this is the
            # final playhead (how far into the item the viewer got), not the
            # wall-clock time between start and stop that the activity-log
            # backends record. Resuming an item mid-way counts the whole offset.
            watched = vo // 1000
            if dur > 0:
                watched = min(watched, dur // 1000)
            if watched < _MIN_WATCH_SECONDS:
                await session.execute(
                    text(
                        "DELETE FROM plex_playback_sessions_active"
                        " WHERE instance_id = :instance_id AND plex_session_key = :k"
                    ),
                    {"instance_id": instance_id, "k": pk},
                )
                continue
            await session.execute(
                text(
                    "INSERT INTO plex_playback_sessions ("
                    " instance_id, account_id, account_title, rating_key, item_type, title,"
                    " grandparent_title, parent_title, plex_session_key,"
                    " start_time, end_time, watched_seconds)"
                    " VALUES ("
                    " :instance_id, :account_id, :account_title, :rating_key, :item_type, :title,"
                    " :grandparent_title, :parent_title, :plex_session_key,"
                    " :start_time, :end_time, :watched_seconds)"
                ),
                {
                    "instance_id": instance_id,
                    "account_id": row.get("account_id"),
                    "account_title": row.get("account_title"),
                    "rating_key": row.get("rating_key"),
                    "item_type": row.get("item_type"),
                    "title": row.get("title"),
                    "grandparent_title": row.get("grandparent_title"),
                    "parent_title": row.get("parent_title"),
                    "plex_session_key": pk,
                    "start_time": start_iso,
                    "end_time": now_iso,
                    "watched_seconds": watched,
                },
            )
            if _snapshot_since_utc is None or start_iso < _snapshot_since_utc:
                _snapshot_since_utc = start_iso
            await session.execute(
                text(
                    "DELETE FROM plex_playback_sessions_active"
                    " WHERE instance_id = :instance_id AND plex_session_key = :k"
                ),
                {"instance_id": instance_id, "k": pk},
            )
        await session.commit()


def _display_entry_from_row(r: dict[str, Any]) -> dict[str, Any]:
    end_time = r.get("end_time") or ""
    date_str = ""
    if end_time:
        try:
            dtp = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            date_str = dtp.strftime("%Y-%m-%dT%H:%M:%S")
        except (TypeError, ValueError):
            date_str = end_time[:19] if len(end_time) >= 19 else end_time
    title = r.get("title") or ""
    parent = r.get("grandparent_title") or r.get("parent_title") or ""
    name = f"{parent} \u2014 {title}" if parent else title
    return {
        "date": date_str,
        "user_id": r.get("account_id"),
        "type": r.get("item_type") or "",
        "name": name,
        "overview": None,
        "rating_key": r.get("rating_key"),
        "item_id": r.get("rating_key"),
    }


async def get_entries(
    instance_id: int,
    min_date: str | None = None,
    max_date: str | None = None,
    user_id: int | None = None,
    type_filter: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = (
        "SELECT instance_id, account_id, rating_key, item_type, title, grandparent_title,"
        " parent_title, end_time"
        " FROM plex_playback_sessions WHERE instance_id = :instance_id"
    )
    params: dict[str, Any] = {"instance_id": instance_id}
    if min_date:
        query += " AND left(end_time, 10) >= :min_date"
        params["min_date"] = min_date
    if max_date:
        query += " AND left(end_time, 10) <= :max_date"
        params["max_date"] = max_date
    if user_id is not None:
        query += " AND account_id = :user_id"
        params["user_id"] = user_id
    if type_filter:
        query += " AND item_type = :type_filter"
        params["type_filter"] = type_filter
    query += " ORDER BY end_time DESC"
    if limit is not None and limit > 0:
        query += " LIMIT :limit"
        params["limit"] = limit
    if offset:
        query += " OFFSET :offset"
        params["offset"] = int(offset)
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        rows = [dict(x) for x in result.mappings().fetchall()]
    return [_display_entry_from_row(x) for x in rows]


async def count_entries(instance_id: int, user_id: int | None = None) -> int:
    query = (
        "SELECT COUNT(*) FROM plex_playback_sessions WHERE instance_id = :instance_id"
    )
    params: dict[str, Any] = {"instance_id": instance_id}
    if user_id is not None:
        query += " AND account_id = :user_id"
        params["user_id"] = user_id
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        row = result.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def get_distinct_types(instance_id: int) -> list[str]:
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT DISTINCT item_type FROM plex_playback_sessions"
                " WHERE instance_id = :instance_id AND item_type IS NOT NULL"
                " ORDER BY item_type"
            ),
            {"instance_id": instance_id},
        )
        return [row[0] for row in result.fetchall()]
