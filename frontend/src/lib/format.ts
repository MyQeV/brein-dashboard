/** Shared formatters. The API returns raw values; display formatting is ours. */

export function formatDuration(seconds: number): string {
  if (!seconds) return "0m";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (hours === 0) return `${minutes}m`;
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
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

export function formatCount(value: number): string {
  return value.toLocaleString();
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
 * Formatted on the server in a fixed zone so the value does not shift with the
 * viewer's clock, and does not differ between server and client render.
 */
export function formatDateTime(value: unknown, timeZone = "UTC"): string {
  if (typeof value !== "string" || !value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-GB", {
    timeZone,
    dateStyle: "short",
    timeStyle: "short",
  });
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
