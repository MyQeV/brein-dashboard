/**
 * Seconds per calendar day from `watch_time_per_user_per_day` rows
 * (`{ date, instance_id, user_id, display_name, total_seconds }`), oldest
 * first — the hero tile's sparkline. A day without rows is zero watch time,
 * not missing data, so every calendar day from `startDate` to `endDate`
 * inclusive is emitted, `0` where no rows landed. If either date is
 * malformed, falls back to the sorted days actually present in the rows.
 */
export function watchTimePerDay(
  rows: unknown[],
  startDate: string,
  endDate: string,
): number[] {
  const byDay = new Map<string, number>();
  for (const entry of rows) {
    if (!entry || typeof entry !== "object") continue;
    const row = entry as Record<string, unknown>;
    if (typeof row.date !== "string" || !row.date) continue;
    const seconds = typeof row.total_seconds === "number" ? row.total_seconds : 0;
    byDay.set(row.date, (byDay.get(row.date) ?? 0) + seconds);
  }

  // Parsed at UTC noon like previous-range.ts: a bare date at midnight lands
  // a day early west of Greenwich.
  const start = new Date(`${startDate}T12:00:00Z`).getTime();
  const end = new Date(`${endDate}T12:00:00Z`).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) {
    return [...byDay.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([, seconds]) => seconds);
  }

  const days: number[] = [];
  const DAY_MS = 86_400_000;
  for (let ms = start; ms <= end; ms += DAY_MS) {
    const day = new Date(ms).toISOString().slice(0, 10);
    days.push(byDay.get(day) ?? 0);
  }
  return days;
}
