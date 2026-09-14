"""Store for Plex users (plex.tv home users) per instance."""

import logging
from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory

log = logging.getLogger(__name__)


def _row_dict_from_item(
    item: dict[str, Any], instance_id: int
) -> dict[str, Any] | None:
    """Build a parameter dict for plex_users from a plex.tv home user object."""
    user_id = item.get("id")
    if user_id is None:
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return {
        "instance_id": instance_id,
        "user_id": user_id,
        "uuid": (str(item["uuid"])[:256] if item.get("uuid") else None),
        "title": (str(item["title"])[:512] if item.get("title") else None),
        "username": (str(item["username"])[:256] if item.get("username") else None),
        "email": (str(item["email"])[:256] if item.get("email") else None),
        "thumb": (str(item["thumb"])[:512] if item.get("thumb") else None),
        "home": 1 if item.get("home") else 0,
        "restricted": 1 if item.get("restricted") else 0,
        "admin": 1 if item.get("admin") else 0,
        "is_deleted": 0,
    }


async def upsert_users(instance_id: int, users: list[dict[str, Any]]) -> None:
    """Upsert Plex users for an instance."""
    if not users:
        return
    rows = [
        r for item in users if (r := _row_dict_from_item(item, instance_id)) is not None
    ]
    if not rows:
        return
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO plex_users"
                " (instance_id, user_id, uuid, title, username, email, thumb,"
                "  home, restricted, admin, is_deleted)"
                " VALUES"
                " (:instance_id, :user_id, :uuid, :title, :username, :email, :thumb,"
                "  :home, :restricted, :admin, :is_deleted)"
                " ON CONFLICT (instance_id, user_id) DO UPDATE SET"
                "  uuid = EXCLUDED.uuid,"
                "  title = EXCLUDED.title,"
                "  username = EXCLUDED.username,"
                "  email = EXCLUDED.email,"
                "  thumb = EXCLUDED.thumb,"
                "  home = EXCLUDED.home,"
                "  restricted = EXCLUDED.restricted,"
                "  admin = EXCLUDED.admin,"
                "  is_deleted = EXCLUDED.is_deleted"
            ),
            rows,
        )
        await session.commit()


async def replace_users(instance_id: int, users: list[dict[str, Any]]) -> None:
    """Soft-replace Plex users: upsert the fresh list, then flag whoever is gone.

    Upsert first. Marking everyone deleted in its own committed transaction and
    upserting afterwards meant a failed upsert left the instance with no visible
    users at all — `get_users` filters on `is_deleted = 0` — until the next
    successful sync.
    """
    if not users:
        return
    await upsert_users(instance_id, users)
    keep = [
        str(r["user_id"])
        for item in users
        if (r := _row_dict_from_item(item, instance_id)) is not None
    ]
    if not keep:
        return
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE plex_users SET is_deleted = 1"
                " WHERE instance_id = :instance_id"
                "   AND CAST(user_id AS TEXT) <> ALL(:keep)"
            ),
            {"instance_id": instance_id, "keep": keep},
        )
        await session.commit()


async def get_users(
    instance_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return Plex users, optionally for one instance. Ordered by title ASC."""
    query = (
        "SELECT instance_id, user_id, uuid, title, username, email, thumb,"
        " home, restricted, admin, is_deleted FROM plex_users"
        " WHERE is_deleted = 0"
    )
    params: dict[str, Any] = {}
    if instance_id is not None:
        query += " AND instance_id = :instance_id"
        params["instance_id"] = instance_id
    query += " ORDER BY title ASC"
    async with get_session_factory()() as session:
        result = await session.execute(text(query), params)
        return [dict(r) for r in result.mappings().fetchall()]
