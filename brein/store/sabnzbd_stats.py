"""Persist SABnzbd server_stats snapshots for KPIs and daily charts."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, asc, delete, desc, select
from brein import config as brein_config
from brein.db import get_session_factory
from brein.integrations.api.sabnzbd import parse_server_stats_daily_timeline
from brein.models.tables import SabnzbdServerStatsSnapshot

# Hourly JSONB snapshots were never pruned. The daily chart reads the newest
# payload's own per-day timeline, or falls back to day-over-day deltas of the
# stored rows, so more than a year of history serves nothing.
RETENTION_DAYS = 400


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(brein_config.TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_date(dt: datetime) -> date:
    return _to_utc(dt).astimezone(_tz()).date()


async def insert_snapshot(instance_id: int, payload: dict[str, Any]) -> None:
    """Insert one server_stats snapshot; parse byte totals for KPIs and charts."""
    from brein.integrations.api.sabnzbd import parse_server_stats_bytes

    bt, bw, bm, btot = parse_server_stats_bytes(payload)
    row = SabnzbdServerStatsSnapshot(
        instance_id=instance_id,
        payload=payload,
        bytes_today=bt,
        bytes_week=bw,
        bytes_month=bm,
        bytes_total=btot,
    )
    factory = get_session_factory()
    async with factory() as s:
        s.add(row)
        await s.commit()


async def prune_snapshots(
    instance_id: int, retention_days: int = RETENTION_DAYS
) -> int:
    """Delete this instance's snapshots older than the retention. Returns rows removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    factory = get_session_factory()
    async with factory() as s:
        result = await s.execute(
            delete(SabnzbdServerStatsSnapshot).where(
                SabnzbdServerStatsSnapshot.instance_id == instance_id,
                SabnzbdServerStatsSnapshot.collected_at < cutoff,
            )
        )
        await s.commit()
        return result.rowcount or 0


async def get_latest_snapshot(
    instance_id: int,
) -> SabnzbdServerStatsSnapshot | None:
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(SabnzbdServerStatsSnapshot)
            .where(SabnzbdServerStatsSnapshot.instance_id == instance_id)
            .order_by(desc(SabnzbdServerStatsSnapshot.collected_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def _daily_series_from_snapshots_delta(
    instance_id: int,
    start: date,
    end: date,
) -> tuple[list[str], list[float]]:
    """GB per day from stored snapshot rows (``bytes_total`` delta, else ``bytes_today``)."""
    tz = _tz()
    extended_start = start - timedelta(days=1)
    range_start_local = datetime.combine(extended_start, time.min, tzinfo=tz)
    range_end_local = datetime.combine(end, time(23, 59, 59, 999999), tzinfo=tz)
    start_utc = range_start_local.astimezone(timezone.utc)
    end_utc = range_end_local.astimezone(timezone.utc)

    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(SabnzbdServerStatsSnapshot)
            .where(
                and_(
                    SabnzbdServerStatsSnapshot.instance_id == instance_id,
                    SabnzbdServerStatsSnapshot.collected_at >= start_utc,
                    SabnzbdServerStatsSnapshot.collected_at <= end_utc,
                )
            )
            .order_by(asc(SabnzbdServerStatsSnapshot.collected_at))
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    best: dict[date, SabnzbdServerStatsSnapshot] = {}
    for row in rows:
        ld = _local_date(row.collected_at)
        prev = best.get(ld)
        if prev is None or row.collected_at > prev.collected_at:
            best[ld] = row

    labels: list[str] = []
    gigabytes: list[float] = []
    d = start
    while d <= end:
        labels.append(d.isoformat())
        d_prev = d - timedelta(days=1)
        row_d = best.get(d)
        row_prev = best.get(d_prev)

        gb = 0.0
        if row_d is not None:
            tot_d = row_d.bytes_total
            tot_prev = row_prev.bytes_total if row_prev is not None else None
            bt = row_d.bytes_today

            if tot_d is not None and tot_prev is not None:
                delta = tot_d - tot_prev
                if delta >= 0:
                    gb = delta / 1_000_000_000.0
                elif bt is not None:
                    gb = bt / 1_000_000_000.0
            elif bt is not None:
                gb = bt / 1_000_000_000.0

        gigabytes.append(round(max(0.0, gb), 4))
        d += timedelta(days=1)

    return labels, gigabytes


async def get_daily_series_gigabytes(
    instance_id: int,
    start: date,
    end: date,
) -> tuple[list[str], list[float]]:
    """Return (ISO date labels, GB per calendar day in ``start``..``end`` inclusive).

    Prefer **SABnzbd's per-day timeline** from the latest stored ``server_stats``
    payload (``servers[*].daily``), summed across servers. That matches the JSON
    SABnzbd already maintains per calendar day.

    If that timeline is empty (old client / missing keys), fall back to day-over-day
    ``bytes_total`` deltas from stored snapshots.
    """
    if start > end:
        return [], []

    latest = await get_latest_snapshot(instance_id)
    if latest and latest.payload:
        by_day = parse_server_stats_daily_timeline(latest.payload)
        if by_day:
            labels: list[str] = []
            gigabytes: list[float] = []
            d = start
            while d <= end:
                iso = d.isoformat()
                labels.append(iso)
                raw = by_day.get(iso, 0)
                gigabytes.append(round(max(0.0, raw / 1_000_000_000.0), 4))
                d += timedelta(days=1)
            return labels, gigabytes

    return await _daily_series_from_snapshots_delta(instance_id, start, end)
