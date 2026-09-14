"""Shared SQL query-building helpers for metrics modules."""

from datetime import date, timedelta
from typing import Any


def _local_date_expr(col: str, tz_param: str = "tz") -> str:
    """Return a SQL expression that converts a UTC ISO timestamp column to a local date string.

    Returns a text value in YYYY-MM-DD format so it can be compared directly with
    Python string date parameters (asyncpg requires date objects for ::date comparisons).
    The caller must include {tz_param} in their query params dict.
    """
    return f"to_char((LEFT({col}, 19)::timestamp AT TIME ZONE 'UTC' AT TIME ZONE :{tz_param}), 'YYYY-MM-DD')"


def _instance_filter(
    instance_id: int | list[int] | None, column: str = "instance_id"
) -> tuple[str, dict[str, Any]]:
    """Return (WHERE fragment, params) for instance filter. Integer IDs formatted inline (safe)."""
    if instance_id is None:
        return "", {}
    if isinstance(instance_id, list):
        if not instance_id:
            return "", {}
        ids_str = ",".join(str(int(i)) for i in instance_id)
        return f" AND {column} IN ({ids_str})", {}
    return f" AND {column} = :iid", {"iid": int(instance_id)}


def _user_instance_filter(
    user_keys: list[str] | None,
    instance_col: str = "s.instance_id",
    user_col: str = "CAST(s.user_id AS TEXT)",
) -> tuple[str, dict[str, Any]]:
    """Return compound (instance_id, user_id) WHERE fragment from 'instance_id:user_id' keys.

    Scopes each user_id to its originating instance, preventing cross-instance ID collisions
    where two different users on different servers share the same numeric user_id.
    """
    if not user_keys:
        return "", {}
    pairs: list[str] = []
    params: dict[str, Any] = {}
    for i, key in enumerate(user_keys):
        # keys without an instance prefix are skipped to avoid cross-instance matches
        if ":" not in key:
            continue
        inst_str, uid = key.split(":", 1)
        try:
            params[f"inst_{i}"] = int(inst_str)
        except ValueError:
            # A malformed prefix is a filter that matches nobody, not a 500.
            params.pop(f"inst_{i}", None)
            continue
        params[f"uid_{i}"] = uid
        pairs.append(f"(:inst_{i}, :uid_{i})")
    if not pairs:
        # The caller asked to filter and nothing survived parsing. Returning an
        # empty fragment would drop the filter and answer for *every* user.
        return " AND 1 = 0", {}
    return f" AND ({instance_col}, {user_col}) IN ({', '.join(pairs)})", params


# A pre-filter on the raw ISO text column, alongside the exact local-date
# predicate. The local-date expression converts every row before comparing, so
# it can use no index and the planner's estimate is far out; a plain text range
# on the same column can, because ISO-8601 sorts chronologically. Measured on
# 30k sessions: a sequential scan of 20.7ms becomes a 5.7ms index-only scan.
#
# The window is deliberately a day wider each way, so no timezone offset can
# push a row that belongs in the range outside it. The exact predicate still
# decides which rows actually count.
_UTC_TEXT_WINDOW = " AND s.start_time >= :utc_lo AND s.start_time < :utc_hi"

# The same predicate for the single-table queries that use no alias.
_UTC_TEXT_WINDOW_BARE = " AND start_time >= :utc_lo AND start_time < :utc_hi"


def _utc_window_params(start_date: str, end_date: str) -> dict[str, str]:
    """Bounds for `_UTC_TEXT_WINDOW`, padded by a day on either side."""
    try:
        lo = date.fromisoformat(start_date) - timedelta(days=1)
        hi = date.fromisoformat(end_date) + timedelta(days=2)
    except ValueError:
        # Callers validate dates; if one slips through, a window that cannot
        # exclude anything is safer than raising from a query builder.
        return {"utc_lo": "", "utc_hi": "9999-12-31"}
    return {"utc_lo": lo.isoformat(), "utc_hi": hi.isoformat()}


def _date_range_where(
    start_date: str, end_date: str, column: str = "stat_date"
) -> tuple[str, dict[str, str]]:
    """Return (AND fragment, params) for date-range filter."""
    return (
        f" AND {column} >= :start_date AND {column} <= :end_date",
        {"start_date": start_date, "end_date": end_date},
    )
