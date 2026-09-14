"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { CONTROL_HEIGHT } from "@/components/ui/control";

/** Matches the old dashboard's preset row exactly. */
const PRESETS = [
  { label: "Today", days: 0 },
  { label: "7d", days: 7 },
  { label: "14d", days: 14 },
  { label: "30d", days: 30 },
  { label: "Year", days: 365 },
  { label: "All", days: "all" as const },
];

/** Tabs whose pages default to today when the URL carries no dates. */
const TODAY_BY_DEFAULT = new Set([
  "/dashboard",
  "/dashboard/movies",
  "/dashboard/series",
]);

/** The floor the old dashboard sent for "All"; predates any playback data. */
const ALL_START_DATE = "2000-01-01";

const DATE_INPUT = `${CONTROL_HEIGHT.sm} min-w-0 flex-1 rounded-md border border-border bg-surface px-2 text-sm max-lg:px-1 max-lg:[&::-webkit-calendar-picker-indicator]:hidden lg:flex-none`;

function isoDaysBefore(endDate: string, days: number): string {
  const end = new Date(`${endDate}T00:00:00Z`);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - days);
  return start.toISOString().slice(0, 10);
}

function shiftIso(date: string, days: number): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

/** Inclusive length of a range, in days. */
function spanDays(startDate: string, endDate: string): number {
  const start = new Date(`${startDate}T00:00:00Z`).getTime();
  const end = new Date(`${endDate}T00:00:00Z`).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return -1;
  return Math.round((end - start) / 86_400_000) + 1;
}

/**
 * Which preset, if any, the current range *is* — for when the URL no longer
 * says. Returns "" when it matches none, which leaves every button unpressed
 * rather than lighting one at random.
 */
function matchPreset(
  startDate: string,
  endDate: string,
  todayByDefault: boolean,
): string {
  if (startDate <= ALL_START_DATE) return "all";
  const span = spanDays(startDate, endDate);
  if (span === 1) return todayByDefault ? "0" : "";
  const preset = PRESETS.find(
    (option) => typeof option.days === "number" && option.days === span,
  );
  return preset ? String(preset.days) : "";
}

/**
 * Presets are computed from the range the server reports, not from the
 * browser's clock: the API works in the app timezone, and around midnight the
 * two disagree by a day.
 */
export function DateRange({
  startDate,
  endDate,
}: {
  startDate: string;
  endDate: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  // `days` is deleted whenever the range stops being a preset — a typed date,
  // or a step with ‹/›. Falling straight back to the tab's default then lit
  // "Today" over a month-long custom range. The URL wins when it has a
  // preset; otherwise the range itself decides, and an unrecognised span
  // lights nothing.
  const active =
    params.get("days") ?? matchPreset(startDate, endDate, TODAY_BY_DEFAULT.has(pathname));

  /** Preserves instance and user filters, which live in the same URL. */
  function push(next: Record<string, string | undefined>) {
    const query = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(next)) {
      if (value === undefined) query.delete(key);
      else query.set(key, value);
    }
    router.push(`${pathname}?${query.toString()}`);
  }

  function applyPreset(days: number | "all") {
    if (days === "all") {
      // The API has no "all" mode: with no dates it falls back to the last
      // seven days, which made "All" report *less* than "Year". Send the same
      // floor the old dashboard used instead.
      push({ days: "all", start_date: ALL_START_DATE, end_date: endDate });
      return;
    }
    push({
      days: String(days),
      start_date: isoDaysBefore(endDate, days === 0 ? 0 : days - 1),
      end_date: endDate,
    });
  }

  /** Steps the window by its own length, so "previous" means the prior period. */
  function shiftPeriod(direction: -1 | 1) {
    const start = new Date(`${startDate}T00:00:00Z`).getTime();
    const end = new Date(`${endDate}T00:00:00Z`).getTime();
    const span = Math.round((end - start) / 86_400_000) + 1;
    push({
      start_date: shiftIso(startDate, direction * span),
      end_date: shiftIso(endDate, direction * span),
      days: undefined,
    });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* One row on a phone too: the two dates share whatever width is
          left between the arrows, rather than the row breaking after the
          dash with the end date and › on a line of their own. That takes
          dropping the dash and the picker icon there — tapping the field
          opens the picker anyway. */}
      <div className="flex w-full items-center gap-2 lg:w-auto">
        <Button
          size="sm"
          variant="secondary"
          aria-label="Previous period"
          onClick={() => shiftPeriod(-1)}
        >
          ‹
        </Button>

        <input
          type="date"
          aria-label="Start date"
          value={startDate}
          onChange={(event) => push({ start_date: event.target.value, days: undefined })}
          className={DATE_INPUT}
        />
        <span className="text-muted max-lg:hidden">–</span>
        <input
          type="date"
          aria-label="End date"
          value={endDate}
          onChange={(event) => push({ end_date: event.target.value, days: undefined })}
          className={DATE_INPUT}
        />

        <Button
          size="sm"
          variant="secondary"
          aria-label="Next period"
          onClick={() => shiftPeriod(1)}
        >
          ›
        </Button>
      </div>

      {/* The six presets fill a row of their own on a phone. */}
      <fieldset className="flex w-full gap-1 border-0 p-0 lg:w-auto">
        <legend className="sr-only">Date range presets</legend>
        {PRESETS.map((preset) => (
          <Button
            key={String(preset.days)}
            size="sm"
            variant={active === String(preset.days) ? "primary" : "ghost"}
            aria-pressed={active === String(preset.days)}
            onClick={() => applyPreset(preset.days)}
            className="flex-1 max-lg:px-2 lg:flex-none"
          >
            {preset.label}
          </Button>
        ))}
      </fieldset>

      <Button size="sm" variant="secondary" onClick={() => router.refresh()}>
        Refresh
      </Button>
      <Button size="sm" variant="secondary" onClick={() => router.push(pathname)}>
        Reset
      </Button>
    </div>
  );
}
