/** Dates are read at UTC noon: parsing a bare date at midnight lands a day early west of Greenwich. */
function parse(date: string): number {
  return new Date(`${date}T12:00:00Z`).getTime();
}

function iso(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

const DAY_MS = 86_400_000;

/** Longer than this and "previous" is not a comparison anyone reads — the "All" preset. */
const MAX_SPAN_DAYS = 366;

/**
 * The window of the same length that ends the day before `startDate`,
 * or null when the range is malformed or too long to compare against.
 */
export function previousRange(
  startDate: string,
  endDate: string,
): { start: string; end: string } | null {
  const start = parse(startDate);
  const end = parse(endDate);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  const spanDays = Math.round((end - start) / DAY_MS) + 1;
  if (spanDays > MAX_SPAN_DAYS) return null;
  return {
    start: iso(start - spanDays * DAY_MS),
    end: iso(start - DAY_MS),
  };
}
