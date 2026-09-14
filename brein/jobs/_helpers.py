"""Tiny shared helpers for job/sync workers."""

from typing import Any


def instance_id_int(inst: dict[str, Any]) -> int | None:
    """Return integer instance id for store calls; None if the value isn't usable."""
    raw = inst.get("id")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
