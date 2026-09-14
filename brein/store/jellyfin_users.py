"""Store for Jellyfin users (Users/Query) per instance."""

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
    """Build a parameter dict for jellyfin_users from an API UserDto."""
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
        "is_deleted": 0,
    }


async def upsert_users(instance_id: int, users: list[dict[str, Any]]) -> None:
    """Upsert Jellyfin users for an instance."""
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
                "INSERT INTO jellyfin_users"
                " (instance_id, user_id, name, server_id, prefix, has_password,"
                "  has_configured_password, date_created, last_login_date,"
                "  last_activity_date, primary_image_tag, is_administrator, is_disabled,"
                "  locked_out_date, enable_all_folders, invalid_login_attempt_count,"
                "  enabled_folders, is_deleted)"
                " VALUES"
                " (:instance_id, :user_id, :name, :server_id, :prefix, :has_password,"
                "  :has_configured_password, :date_created, :last_login_date,"
                "  :last_activity_date, :primary_image_tag, :is_administrator, :is_disabled,"
                "  :locked_out_date, :enable_all_folders, :invalid_login_attempt_count,"
                "  :enabled_folders, :is_deleted)"
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
                "  is_deleted = EXCLUDED.is_deleted"
            ),
            rows,
        )
        await session.commit()


async def replace_users(instance_id: int, users: list[dict[str, Any]]) -> None:
    """Soft-replace Jellyfin users: upsert the fresh list, then flag whoever is gone.

    Upsert first, as the Emby store does. Marking everyone deleted in its own
    committed transaction and upserting afterwards meant a failed upsert left
    the instance with no visible users at all — `get_users` filters on
    `is_deleted = 0` — until a later sync happened to succeed. An empty list is
    a failed fetch far more often than an emptied server, so it is refused
    rather than applied.
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
                "UPDATE jellyfin_users SET is_deleted = 1"
                " WHERE instance_id = :instance_id"
                "   AND CAST(user_id AS TEXT) <> ALL(:keep)"
            ),
            {"instance_id": instance_id, "keep": keep},
        )
        await session.commit()


async def get_users(
    instance_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return Jellyfin users, optionally for one instance. Ordered by name ASC."""
    query = (
        "SELECT instance_id, user_id, name, server_id, date_created, last_login_date,"
        " last_activity_date, primary_image_tag, is_administrator, is_disabled,"
        " locked_out_date, enable_all_folders, invalid_login_attempt_count,"
        " enabled_folders, is_deleted FROM jellyfin_users"
    )
    params: dict[str, Any] = {}
    if instance_id is not None:
        query += " WHERE instance_id = :instance_id"
        params["instance_id"] = instance_id
    query += " ORDER BY name ASC"
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        return [dict(r) for r in result.mappings().fetchall()]


async def count_users_by_instance() -> dict[int, int]:
    """Return {instance_id: count} of non-deleted Jellyfin users per instance."""
    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT instance_id, COUNT(*) AS cnt FROM jellyfin_users"
                " WHERE is_deleted = 0 GROUP BY instance_id"
            )
        )
        return {int(r[0]): int(r[1]) for r in result.fetchall()}
