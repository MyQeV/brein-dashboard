"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import {
  type Period,
  periodOf,
  periodToDate,
  shiftRange,
  todayIn,
} from "@/lib/calendar-range";
import { useTimeZone } from "@/lib/timezone-context";

type PresetKey = "today" | Period | "all";

/**
 * Calendar periods, not rolling day counts: "Week" runs from Monday and
 * "Month" from the 1st, so the numbers line up with how people talk about
 * them. Each ends today — the future has nothing to show. The hints feed
 * the info popover.
 */
const PRESETS: { key: PresetKey; label: string; hint: string }[] = [
  { key: "today", label: "Today", hint: "The current day." },
  { key: "week", label: "Week", hint: "This week so far, from Monday." },
  { key: "month", label: "Month", hint: "This month so far, from the 1st." },
  { key: "year", label: "Year", hint: "This year so far, from 1 January." },
  { key: "all", label: "All", hint: "Everything on record." },
];

/** The floor the old dashboard sent for "All"; predates any playback data. */
const ALL_START_DATE = "2000-01-01";

const DATE_INPUT = `${CONTROL_HEIGHT.sm} min-w-0 flex-1 rounded-md border border-border bg-surface px-2 text-sm max-lg:px-1 max-lg:[&::-webkit-calendar-picker-indicator]:hidden lg:flex-none`;

/** What each preset covers, anchored on today in the app zone. */
function presetRanges(today: string): Record<PresetKey, { start: string; end: string }> {
  return {
    today: { start: today, end: today },
    week: periodToDate("week", today),
    month: periodToDate("month", today),
    year: periodToDate("year", today),
    // The API has no "all" mode: with no dates it falls back to the last
    // seven days, which made "All" report *less* than "Year". Send the same
    // floor the old dashboard used instead.
    all: { start: ALL_START_DATE, end: today },
  };
}

/**
 * Which preset the current range *is*. Exact matches only: a past week is
 * not "Week", which promises the current one, so it lights nothing rather
 * than something misleading. Presets that cover the same days — "Today" and
 * "Week" on a Monday — are told apart by `period`, the one the URL says was
 * chosen.
 */
function matchPreset(
  ranges: Record<PresetKey, { start: string; end: string }>,
  startDate: string,
  endDate: string,
  period: Period | null,
): PresetKey | "" {
  if (startDate <= ALL_START_DATE) return "all";
  const covers = (key: PresetKey) =>
    ranges[key].start === startDate && ranges[key].end === endDate;
  if (period && covers(period)) return period;
  const match = PRESETS.find(({ key }) => covers(key));
  return match ? match.key : "";
}

/** The ⓘ beside the presets: what each one covers, and what ‹ › do. */
function PresetHelp() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        aria-label="What the presets cover"
        aria-expanded={open}
        aria-controls="preset-help"
        onClick={() => setOpen((value) => !value)}
        className={`${CONTROL_HEIGHT.sm} grid aspect-square place-items-center rounded-md text-muted hover:text-text`}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <circle cx="10" cy="10" r="8" />
          <path d="M10 9v5M10 6.2v.3" />
        </svg>
      </button>

      {open && (
        <div
          id="preset-help"
          className="absolute right-0 z-(--z-dropdown) mt-2 w-72 rounded-lg border border-border bg-surface p-3 text-sm shadow-(--shadow-elevated)"
        >
          <dl className="flex flex-col gap-1.5">
            {PRESETS.map((preset) => (
              <div key={preset.key} className="flex gap-2">
                <dt className="w-12 shrink-0 font-medium">{preset.label}</dt>
                <dd className="text-muted">{preset.hint}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-muted">
            ‹ and › step to the previous or next period of the same kind, never past
            today. Dates follow the app's time zone.
          </p>
        </div>
      )}
    </div>
  );
}

export function DateRange({
  startDate,
  endDate,
  period: periodHint,
}: {
  startDate: string;
  endDate: string;
  /** The `period` the URL carries: which preset picked these dates, if one did. */
  period: Period | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const timeZone = useTimeZone();
  // Today in the app zone, as the API resolves it: the browser's own clock
  // disagrees by a day around midnight and would light the wrong preset.
  const today = todayIn(timeZone);
  const ranges = presetRanges(today);
  // The calendar period the range is, if any. The dates alone cannot tell a
  // Monday on its own from the week so far, so the URL's word settles it.
  const period = periodOf(startDate, endDate, today, periodHint);
  const active = matchPreset(ranges, startDate, endDate, period);
  // Null once the range ends today: the future is out of bounds, so › is off.
  const nextRange = shiftRange(startDate, endDate, 1, today, period);

  /** Preserves instance and user filters, which live in the same URL. */
  function push(next: Record<string, string | undefined>) {
    const query = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(next)) {
      if (value === undefined) query.delete(key);
      else query.set(key, value);
    }
    router.push(`${pathname}?${query.toString()}`);
  }

  /** A hand-picked date is whatever it is: the preset's word no longer holds. */
  function pickDate(next: { start_date: string } | { end_date: string }) {
    push({ ...next, period: undefined });
  }

  function applyPreset(key: PresetKey) {
    const range = ranges[key];
    push({
      start_date: range.start,
      end_date: range.end,
      period: key === "today" || key === "all" ? undefined : key,
    });
  }

  /** Steps to the neighbouring period: last month, not the 31 days before it. */
  function shiftPeriod(direction: -1 | 1) {
    const range =
      direction === 1 ? nextRange : shiftRange(startDate, endDate, -1, today, period);
    if (range)
      push({ start_date: range.start, end_date: range.end, period: period ?? undefined });
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
          max={endDate < today ? endDate : today}
          onChange={(event) => pickDate({ start_date: event.target.value })}
          className={DATE_INPUT}
        />
        <span className="text-muted max-lg:hidden">–</span>
        <input
          type="date"
          aria-label="End date"
          value={endDate}
          min={startDate}
          max={today}
          onChange={(event) => pickDate({ end_date: event.target.value })}
          className={DATE_INPUT}
        />

        <Button
          size="sm"
          variant="secondary"
          aria-label="Next period"
          disabled={nextRange === null}
          onClick={() => shiftPeriod(1)}
        >
          ›
        </Button>
      </div>

      {/* The presets and their ⓘ fill a row of their own on a phone. */}
      <fieldset className="flex w-full items-center gap-1 border-0 p-0 lg:w-auto">
        <legend className="sr-only">Date range presets</legend>
        {PRESETS.map((preset) => (
          <Button
            key={preset.key}
            size="sm"
            variant={active === preset.key ? "primary" : "ghost"}
            aria-pressed={active === preset.key}
            onClick={() => applyPreset(preset.key)}
            className="flex-1 max-lg:px-2 lg:flex-none"
          >
            {preset.label}
          </Button>
        ))}
        <PresetHelp />
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
