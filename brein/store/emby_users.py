"""Store for Emby users (Users/Query) per instance."""

import json
import logging
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory

log = logging.getLogger(__name__)


def _bool_to_int(value: Any) -> int | None:
    if value is True:
        return 1
    if value is False:
        return 0
    return None


def _row_dict_from_item(item: dict[str, Any], instance_id: int) -> dict[str, Any]:
    """Build a parameter dict for emby_users from an API UserDto."""
    user_id = str(item.get("Id") or "")
    name = (item.get("Name") or "")[:512] if item.get("Name") else None
    server_id = (item.get("ServerId") or "")[:256] if item.get("ServerId") else None
    prefix_raw = item.get("Prefix")
    prefix = (str(prefix_raw)[:32] or None) if prefix_raw is not None else None
    has_password = _bool_to_int(item.get("HasPassword"))
    has_configured_password = _bool_to_int(item.get("HasConfiguredPassword"))
    date_created = (
        (item.get("DateCreated") or "")[:64] if item.get("DateCreated") else None
    )
    last_login = item.get("LastLoginDate")
    last_login_str = str(last_login)[:64] if last_login else None
    last_activity = item.get("LastActivityDate")
    last_activity_str = str(last_activity)[:64] if last_activity else None
    primary_image_tag = (
        (item.get("PrimaryImageTag") or "")[:256]
        if item.get("PrimaryImageTag")
        else None
    )
    policy = item.get("Policy") or {}
    is_administrator = 1 if policy.get("IsAdministrator") else 0
    is_disabled = 1 if policy.get("IsDisabled") else 0
    locked_out = policy.get("LockedOutDate")
    locked_out_date = str(locked_out) if locked_out is not None else None
    enable_all_folders = 1 if policy.get("EnableAllFolders") else 0
    invalid_login_attempt_count = int(policy.get("InvalidLoginAttemptCount") or 0)
    enabled_folders_list = policy.get("EnabledFolders")
    enabled_folders = (
        json.dumps(enabled_folders_list)
        if isinstance(enabled_folders_list, list)
        else None
    )
    user_item_id_raw = item.get("UserItemId") or item.get("ItemId")
    user_item_id = (
        (str(user_item_id_raw)[:256] or None) if user_item_id_raw is not None else None
    )
    return {
        "instance_id": instance_id,
        "user_id": user_id,
        "name": name,
        "server_id": server_id,
        "prefix": prefix,
        "has_password": has_password,
        "has_configured_password": has_configured_password,
        "date_created": date_created,
        "last_login_date": last_login_str,
        "last_activity_date": last_activity_str,
        "primary_image_tag": primary_image_tag,
        "is_administrator": is_administrator,
        "is_disabled": is_disabled,
        "locked_out_date": locked_out_date,
        "enable_all_folders": enable_all_folders,
        "invalid_login_attempt_count": invalid_login_attempt_count,
        "enabled_folders": enabled_folders,
        "user_item_id": user_item_id,
        "is_deleted": 0,
    }


async def upsert_users(instance_id: int, users: list[dict[str, Any]]) -> None:
    """Upsert Emby users for an instance."""
    if not users:
        return
    rows = [
        _row_dict_from_item(it, instance_id) for it in users if it.get("Id") is not None
    ]
    if not rows:
        return
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO emby_users"
                " (instance_id, user_id, name, server_id, prefix, has_password,"
                "  has_configured_password, date_created, last_login_date,"
                "  last_activity_date, primary_image_tag, is_administrator, is_disabled,"
                "  locked_out_date, enable_all_folders, invalid_login_attempt_count,"
                "  enabled_folders, user_item_id, is_deleted)"
                " VALUES"
                " (:instance_id, :user_id, :name, :server_id, :prefix, :has_password,"
                "  :has_configured_password, :date_created, :last_login_date,"
                "  :last_activity_date, :primary_image_tag, :is_administrator, :is_disabled,"
                "  :locked_out_date, :enable_all_folders, :invalid_login_attempt_count,"
                "  :enabled_folders, :user_item_id, :is_deleted)"
                " ON CONFLICT (instance_id, user_id) DO UPDATE SET"
                "  name = EXCLUDED.name,"
                "  server_id = EXCLUDED.server_id,"
                "  prefix = EXCLUDED.prefix,"
                "  has_password = EXCLUDED.has_password,"
                "  has_configured_password = EXCLUDED.has_configured_password,"
                "  date_created = EXCLUDED.date_created,"
                "  last_login_date = EXCLUDED.last_login_date,"
                "  last_activity_date = EXCLUDED.last_activity_date,"
                "  primary_image_tag = EXCLUDED.primary_image_tag,"
                "  is_administrator = EXCLUDED.is_administrator,"
                "  is_disabled = EXCLUDED.is_disabled,"
                "  locked_out_date = EXCLUDED.locked_out_date,"
                "  enable_all_folders = EXCLUDED.enable_all_folders,"
                "  invalid_login_attempt_count = EXCLUDED.invalid_login_attempt_count,"
                "  enabled_folders = EXCLUDED.enabled_folders,"
                "  user_item_id = COALESCE(EXCLUDED.user_item_id, emby_users.user_item_id),"
                "  is_deleted = EXCLUDED.is_deleted"
            ),
            rows,
        )
        await session.commit()


async def replace_users(instance_id: int, users: list[dict[str, Any]]) -> None:
    """Soft-replace Emby users: upsert the fresh list, then flag whoever is gone.

    Upsert first. Marking everyone deleted in its own committed transaction and
    upserting afterwards meant a failed upsert left the instance with no visible
    users at all — `get_users` filters on `is_deleted = 0` — until the next
    successful sync.
    """
    if not users:
        return
    await upsert_users(instance_id, users)
    keep = [str(it["Id"]) for it in users if it.get("Id") is not None]
    if not keep:
        return
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE emby_users SET is_deleted = 1"
                " WHERE instance_id = :instance_id"
                "   AND CAST(user_id AS TEXT) <> ALL(:keep)"
            ),
            {"instance_id": instance_id, "keep": keep},
        )
        await session.commit()


async def get_users(
    instance_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return Emby users, optionally for one instance. Ordered by name ASC."""
    query = (
        "SELECT instance_id, user_id, name, server_id, date_created, last_login_date,"
        " last_activity_date, primary_image_tag, is_administrator, is_disabled,"
        " locked_out_date, enable_all_folders, invalid_login_attempt_count,"
        " enabled_folders, user_item_id, is_deleted FROM emby_users"
    )
    params: dict[str, Any] = {}
    if instance_id is not None:
        query += " WHERE instance_id = :instance_id"
        params["instance_id"] = instance_id
    query += " ORDER BY name ASC"
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        return [dict(r) for r in result.mappings().fetchall()]


async def has_users_missing_user_item_id(instance_id: int | None = None) -> bool:
    """True if any emby_users row has user_item_id NULL or empty."""
    if instance_id is not None:
        query = (
            "SELECT 1 FROM emby_users"
            " WHERE instance_id = :instance_id"
            " AND (user_item_id IS NULL OR user_item_id = '') LIMIT 1"
        )
        params: dict[str, Any] = {"instance_id": instance_id}
    else:
        query = (
            "SELECT 1 FROM emby_users"
            " WHERE (user_item_id IS NULL OR user_item_id = '') LIMIT 1"
        )
        params = {}
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        return result.fetchone() is not None


async def get_distinct_user_ids_from_activity_log(
    instance_id: int | None = None, limit: int | None = None
) -> list[tuple[int, str]]:
    """Distinct (instance_id, user_id) from activity log, excluding already resolved and 404'd IDs."""
    instance_where = (
        "AND e.instance_id = :instance_id" if instance_id is not None else ""
    )
    limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
    params: dict[str, Any] = {}
    if instance_id is not None:
        params["instance_id"] = instance_id
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                f"""
                SELECT DISTINCT e.instance_id, e.user_id
                FROM emby_activity_log_entries e
                WHERE e.user_id IS NOT NULL AND e.user_id != 0
                  AND NOT EXISTS (
                    SELECT 1 FROM emby_users u
                    WHERE u.instance_id = e.instance_id
                      AND u.user_item_id = CAST(e.user_id AS TEXT)
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM emby_user_item_id_skip s
                    WHERE s.instance_id = e.instance_id
                      AND s.user_id = CAST(e.user_id AS TEXT)
                  )
                  {instance_where}
                {limit_clause}
                """
            ),
            params,
        )
        rows = result.fetchall()
    return [(int(r[0]), str(r[1]).strip()) for r in rows if r[0] is not None and r[1]]


async def has_user_item_id_for_instance(instance_id: int, user_id: str) -> bool:
    """True if some emby_users row for this instance already has user_item_id = user_id."""
    if not user_id or not str(user_id).strip():
        return False
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM emby_users"
                " WHERE instance_id = :instance_id AND user_item_id = :user_id LIMIT 1"
            ),
            {"instance_id": instance_id, "user_id": str(user_id).strip()},
        )
        return result.fetchone() is not None


async def record_user_item_id_skip(instance_id: int, user_id: str) -> None:
    """Record that this activity-log user id cannot be resolved for the instance.

    Either GET /Users/{user_id} failed, or it answered with a guid no
    emby_users row carries. Both are permanent as far as the backfill can
    tell, so the id is never fetched again.
    """
    if not user_id or not user_id.strip():
        return
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO emby_user_item_id_skip (instance_id, user_id)"
                " VALUES (:instance_id, :user_id)"
                " ON CONFLICT DO NOTHING"
            ),
            {"instance_id": instance_id, "user_id": str(user_id).strip()},
        )
        await session.commit()


async def set_user_item_id(instance_id: int, user_guid: str, item_id: str) -> bool:
    """Set user_item_id for the user with the given guid. Returns True if a row was updated."""
    if not user_guid or not item_id:
        return False
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "UPDATE emby_users SET user_item_id = :item_id"
                " WHERE instance_id = :instance_id AND user_id = :user_guid"
            ),
            {
                "item_id": str(item_id).strip(),
                "instance_id": instance_id,
                "user_guid": user_guid.strip(),
            },
        )
        await session.commit()
        return result.rowcount > 0
