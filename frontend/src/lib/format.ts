/** Shared formatters. The API returns raw values; display formatting is ours. */

export function formatDuration(seconds: number): string {
  if (!seconds) return "0m";
  // Rounded to whole minutes first: rounding the remainder on its own made
  // 265h 59m 40s into "265h 60m".
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
}

/** A scheduler interval: exact, so "90m" rather than a rounded "1h". */
export function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0 && seconds >= 3600) return `${seconds / 3600}h`;
  if (seconds % 60 === 0 && seconds >= 60) return `${seconds / 60}m`;
  return `${seconds}s`;
}

/**
 * A playback clock: "4:07", or "1:04:07" once it passes an hour.
 *
 * formatDuration rounds to whole minutes, which is right for a watch-time
 * total and useless for a position that has to tick every second.
 */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

/**
 * Fixed locale, like formatDateTime: these render in client components the
 * server has already rendered, and a browser set to nl-NL would otherwise
 * hydrate "1,234" as "1.234" and warn about the mismatch.
 */
export function formatCount(value: number): string {
  return value.toLocaleString("en-GB");
}

// Indexed by Postgres EXTRACT(DOW), where 0 is Sunday — not ISO, where 1 is
// Monday. Getting this wrong labels every bar in the weekday chart one day off.
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function weekdayLabel(index: number): string {
  return WEEKDAYS[index] ?? String(index);
}

export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/**
 * One `Intl.DateTimeFormat` per locale, zone and option set, kept for the
 * life of the module. Building one costs far more than formatting with it,
 * and `toLocaleString` builds a new one per call — a drill of five hundred
 * sessions paid that for every row each time a day was opened.
 */
const FORMATTERS = new Map<string, Intl.DateTimeFormat>();

export function dateTimeFormatter(
  locale: string,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let formatter = FORMATTERS.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, options);
    FORMATTERS.set(key, formatter);
  }
  return formatter;
}

/**
 * Formatted in a fixed locale and an explicit zone so the value does not shift
 * with the viewer's clock, and does not differ between server and client
 * render. The zone is the app's: `appTimeZone()` in a server component,
 * `useTimeZone()` in a client one, or the `app_timezone` a metrics payload
 * carries. It is required rather than defaulted so that a caller cannot
 * quietly show UTC next to a page showing local time.
 */
export function formatDateTime(value: unknown, timeZone: string): string {
  if (typeof value !== "string" || !value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return dateTimeFormatter("en-GB", {
    timeZone,
    dateStyle: "short",
    timeStyle: "short",
  }).format(parsed);
}

/** Read a dotted path out of an API record. */
export function readPath(row: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => {
    if (value && typeof value === "object" && key in value) {
      return (value as Record<string, unknown>)[key];
    }
    return undefined;
  }, row);
}
