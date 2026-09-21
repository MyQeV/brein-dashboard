/**
 * The calendar periods behind the dashboard's range presets.
 *
 * Dates are bare YYYY-MM-DD strings and every step is done in UTC, so the
 * browser's zone never shifts a boundary; "today" itself is taken in the app
 * zone with `todayIn`, the same zone the API resolves its dates in. Nothing
 * here reaches past today: the future has no playback to show.
 */
export type Period = "week" | "month" | "year";

export type DateSpan = { start: string; end: string };

const PERIODS: readonly Period[] = ["week", "month", "year"];

const DAY_MS = 86_400_000;

/** The `period` a URL carries, or null for anything that is not one. */
export function parsePeriod(value: string | undefined): Period | null {
  return (PERIODS as readonly string[]).includes(value ?? "") ? (value as Period) : null;
}

function parse(date: string): Date {
  return new Date(`${date}T00:00:00Z`);
}

function iso(value: Date): string {
  return value.toISOString().slice(0, 10);
}

/** Today as the API sees it: in the app zone, not the browser's. */
export function todayIn(timeZone: string): string {
  return new Date().toLocaleDateString("en-CA", { timeZone });
}

export function addDays(date: string, days: number): string {
  const value = parse(date);
  value.setUTCDate(value.getUTCDate() + days);
  return iso(value);
}

/** Inclusive length of a range in days, or -1 when either date is malformed. */
export function spanDays(startDate: string, endDate: string): number {
  const start = parse(startDate).getTime();
  const end = parse(endDate).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return -1;
  return Math.round((end - start) / DAY_MS) + 1;
}

/** The whole week (Monday to Sunday), month or year that holds `anchor`. */
export function periodRange(period: Period, anchor: string): DateSpan {
  const date = parse(anchor);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  if (period === "week") {
    const start = addDays(anchor, -((date.getUTCDay() + 6) % 7));
    return { start, end: addDays(start, 6) };
  }
  if (period === "month") {
    return {
      start: iso(new Date(Date.UTC(year, month, 1))),
      end: iso(new Date(Date.UTC(year, month + 1, 0))),
    };
  }
  return {
    start: iso(new Date(Date.UTC(year, 0, 1))),
    end: iso(new Date(Date.UTC(year, 11, 31))),
  };
}

/** The current period so far: from its first day up to today. */
export function periodToDate(period: Period, today: string): DateSpan {
  return { start: periodRange(period, today).start, end: today };
}

/** Whether the range is the whole `period`, or the current one up to today. */
function isPeriod(
  period: Period,
  startDate: string,
  endDate: string,
  today: string,
): boolean {
  const range = periodRange(period, startDate);
  if (range.start !== startDate) return false;
  return endDate === range.end || (endDate === today && today < range.end);
}

/**
 * Which calendar period a range is: a whole one, or the current one to date
 * (Monday to today, the 1st to today), which is as far as the current period
 * can reach. Null for anything else.
 *
 * The dates alone cannot always tell: on a Monday, "Today" and "Week" are
 * the same single day, and when the 1st falls on a Monday the 1st to the 3rd
 * is "Week" or "Month" by choice. The `hint` is what the URL says was
 * chosen; it wins when it fits and is ignored when it does not. Without one,
 * a single day is a day — from "Today" on a Monday, ‹ goes to Sunday — and a
 * longer range is the shortest period it matches.
 */
export function periodOf(
  startDate: string,
  endDate: string,
  today: string,
  hint: Period | null = null,
): Period | null {
  if (hint && isPeriod(hint, startDate, endDate, today)) return hint;
  if (spanDays(startDate, endDate) < 2) return null;
  for (const period of PERIODS) {
    if (isPeriod(period, startDate, endDate, today)) return period;
  }
  return null;
}

/** The range cut off at today, or null when all of it lies ahead. */
export function clampToToday(range: DateSpan, today: string): DateSpan | null {
  if (range.start > today) return null;
  return { start: range.start, end: range.end < today ? range.end : today };
}

/**
 * The range one step earlier (-1) or later (+1), or null when that step
 * would start after today. A calendar period steps to its neighbour — March
 * to February, not to the 31 days before the 1st — and any other range moves
 * by its own length. A step forward ends at today at the latest. The `hint`
 * is `periodOf`'s.
 */
export function shiftRange(
  startDate: string,
  endDate: string,
  direction: -1 | 1,
  today: string,
  hint: Period | null = null,
): DateSpan | null {
  const period = periodOf(startDate, endDate, today, hint);
  const date = parse(startDate);
  let next: DateSpan;
  if (period === "week") {
    next = periodRange("week", addDays(startDate, 7 * direction));
  } else if (period === "month") {
    const anchor = new Date(
      Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + direction, 1),
    );
    next = periodRange("month", iso(anchor));
  } else if (period === "year") {
    const anchor = new Date(Date.UTC(date.getUTCFullYear() + direction, 0, 1));
    next = periodRange("year", iso(anchor));
  } else {
    const span = spanDays(startDate, endDate);
    if (span < 1) return null;
    next = {
      start: addDays(startDate, direction * span),
      end: addDays(endDate, direction * span),
    };
  }
  return clampToToday(next, today);
}
