import {
  addDays,
  type DateSpan,
  type Period,
  periodOf,
  periodRange,
  shiftRange,
  spanDays,
} from "./calendar-range";

/** Longer than this and "previous" is not a comparison anyone reads — the "All" preset. */
const MAX_SPAN_DAYS = 366;

/**
 * The window to compare this one with: the previous calendar week, month or
 * year when the range is a whole one; the same stretch of the previous period
 * when it is the current one to date (the 1st to the 21st against the 1st to
 * the 21st of last month, not against the whole of it); otherwise the same
 * number of days ending the day before `startDate`. Null when the range is
 * malformed or too long to compare against. The `hint` is `periodOf`'s: a
 * Monday alone is "Today" against Sunday, or "Week" against last Monday.
 */
export function previousRange(
  startDate: string,
  endDate: string,
  today: string,
  hint: Period | null = null,
): DateSpan | null {
  const span = spanDays(startDate, endDate);
  if (span < 1 || span > MAX_SPAN_DAYS) return null;
  const period = periodOf(startDate, endDate, today, hint);
  const previous = shiftRange(startDate, endDate, -1, today, period);
  if (!previous) return null;
  if (period && endDate !== periodRange(period, startDate).end) {
    const cut = addDays(previous.start, span - 1);
    return { start: previous.start, end: cut < previous.end ? cut : previous.end };
  }
  return previous;
}
