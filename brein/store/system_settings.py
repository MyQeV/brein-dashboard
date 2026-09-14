"""System settings store: runtime-configurable key-value settings persisted in DB.

Scheduled-job cadence deliberately does NOT live here. The runner reads
``scheduled_tasks.interval_seconds``, and the reconciler's upsert preserves
that column so per-task edits on /settings/tasks survive. A second interval
value here looked editable while changing nothing.

The matching ``BREIN_*_INTERVAL_SECONDS`` environment variables remain: they
feed ``default_interval_seconds`` in the task registry, which the reconciler
applies only when it first inserts a task row. They are seed defaults, not a
live control — retune an existing task on /settings/tasks.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brein import config as brein_config

_SETTINGS_CATALOG: list[dict[str, Any]] = [
    {
        "key": "snapshot_rebuild_interval_seconds",
        "attr": "SNAPSHOT_REBUILD_INTERVAL_SECONDS",
        "label": "Snapshot rebuild interval",
        "value_type": "int",
        "default": 900,
        "unit": "seconds",
        "description": "How often dashboard metric snapshots are rebuilt.",
    },
    {
        "key": "emby_item_cache_max_per_run",
        "attr": "EMBY_ITEM_CACHE_MAX_PER_RUN",
        "label": "Item cache max per run",
        "value_type": "int",
        "default": 200,
        "unit": "items",
        "description": "Maximum items fetched per item sync run.",
    },
    {
        "key": "emby_item_cache_batch_size",
        "attr": "EMBY_ITEM_CACHE_BATCH_SIZE",
        "label": "Item cache batch size",
        "value_type": "int",
        "default": 50,
        "unit": "items",
        "description": "Number of items fetched per batch during item sync.",
    },
    {
        "key": "emby_item_cache_batch_delay_seconds",
        "attr": "EMBY_ITEM_CACHE_BATCH_DELAY_SECONDS",
        "label": "Item cache batch delay",
        "value_type": "float",
        "default": 0.5,
        "unit": "seconds",
        "description": "Delay between item sync batches.",
    },
]


def get_catalog() -> list[dict[str, Any]]:
    return _SETTINGS_CATALOG


async def get_all(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(text("SELECT key, value FROM system_settings"))
    return {row[0]: row[1] for row in result.fetchall()}


async def set_value(session: AsyncSession, key: str, value: str) -> None:
    await session.execute(
        text(
            "INSERT INTO system_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"key": key, "value": value},
    )
    await session.commit()


def cast_value(entry: dict[str, Any], raw: str) -> Any:
    """Coerce a raw string to the entry's declared type. Raises on bad input."""
    vtype = entry["value_type"]
    if vtype == "int":
        return int(raw)
    if vtype == "float":
        return float(raw)
    return raw


# Kept because app.py's Jinja handler still imports the private name; it goes
# when that route does.
_cast_value = cast_value


async def apply_to_config(session: AsyncSession) -> None:
    stored = await get_all(session)
    for entry in _SETTINGS_CATALOG:
        raw = stored.get(entry["key"])
        if raw is None:
            continue
        try:
            setattr(brein_config, entry["attr"], cast_value(entry, raw))
        except (ValueError, TypeError):
            pass


async def get_settings_with_values(session: AsyncSession) -> list[dict[str, Any]]:
    stored = await get_all(session)
    result = []
    for entry in _SETTINGS_CATALOG:
        current_raw = stored.get(entry["key"])
        if current_raw is not None:
            try:
                current = cast_value(entry, current_raw)
            except (ValueError, TypeError):
                current = current_raw
        else:
            current = getattr(brein_config, entry["attr"], entry["default"])
        result.append({**entry, "current": current})
    return result


async def save_settings(session: AsyncSession, values: dict[str, str]) -> list[str]:
    """Validate and persist submitted settings.

    Returns a list of human-readable errors; entries that fail validation are
    left untouched rather than aborting the whole save, so one bad field does
    not discard the others. Blank values mean "unchanged".
    """
    errors: list[str] = []
    by_key = {entry["key"]: entry for entry in _SETTINGS_CATALOG}

    for key, raw in values.items():
        entry = by_key.get(key)
        if entry is None:
            errors.append(f"Unknown setting: {key}")
            continue
        text_value = (raw or "").strip()
        if not text_value:
            continue
        try:
            cast_value(entry, text_value)
        except (ValueError, TypeError):
            errors.append(f"{entry['label']} must be a valid {entry['value_type']}.")
            continue
        await set_value(session, key, text_value)

    await apply_to_config(session)
    return errors
