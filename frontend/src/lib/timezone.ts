/**
 * The zone timestamps are shown in.
 *
 * The API formats "today" in its TZ variable (config.py), and this reads the
 * same one so a page and the dashboard never show one instant two hours
 * apart. Validated the same way the API does it: a typo'd TZ would otherwise
 * throw a RangeError out of every toLocaleString on the page, so it falls
 * back to UTC instead.
 *
 * Server only — a client bundle has no process environment. Client components
 * take the zone from `useTimeZone()` in timezone-context.tsx, which the app
 * layout seeds from here.
 */
export function appTimeZone(): string {
  const raw = (process.env.TZ ?? "").trim();
  return raw && isValidTimeZone(raw) ? raw : "UTC";
}

function isValidTimeZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}
