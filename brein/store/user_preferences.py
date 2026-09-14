"""User preferences store: generic key/value per user (JSON-encoded values)."""

from typing import Any

from sqlalchemy import text

from brein.db import get_session_factory


async def get_all(user_id: str) -> dict[str, Any]:
    """Return all preferences for a user as {key: parsed_value}."""
    import json

    async with get_session_factory()() as session:
        result = await session.execute(
            text("SELECT key, value FROM user_preferences WHERE user_id = :uid"),
            {"uid": user_id},
        )
        out: dict[str, Any] = {}
        for row in result.mappings().fetchall():
            try:
                out[row["key"]] = json.loads(row["value"])
            except Exception:
                out[row["key"]] = row["value"]
        return out


async def delete_preference(user_id: str, key: str) -> None:
    """Delete a single preference."""
    async with get_session_factory()() as session:
        await session.execute(
            text("DELETE FROM user_preferences WHERE user_id = :uid AND key = :key"),
            {"uid": user_id, "key": key},
        )
        await session.commit()


async def delete_by_prefix(user_id: str, prefix: str) -> None:
    """Delete all preferences whose key starts with prefix."""
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "DELETE FROM user_preferences"
                " WHERE user_id = :uid AND key LIKE :pattern"
            ),
            # `_` is a single-character wildcard in LIKE just as `%` is any
            # run, so a prefix like "list_columns_" also matched keys that
            # merely resemble it. Backslash is LIKE's default escape, so the
            # escaping below makes both literal — but only without an ESCAPE
            # clause: `ESCAPE ''` turns escaping *off*, which left every
            # backslash literal and every `_` a wildcard again, so a prefix
            # holding an underscore matched nothing at all.
            {
                "uid": user_id,
                "pattern": prefix.replace("\\", "\\\\")
                .replace("%", r"\%")
                .replace("_", r"\_")
                + "%",
            },
        )
        await session.commit()


async def set_preference(user_id: str, key: str, value: Any) -> None:
    """Upsert a single preference. Value is JSON-encoded."""
    import json

    encoded = json.dumps(value)
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO user_preferences (user_id, key, value)"
                " VALUES (:uid, :key, :val)"
                " ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"uid": user_id, "key": key, "val": encoded},
        )
        await session.commit()
