"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { clientFetch } from "@/lib/client-fetch";
import { cn } from "@/lib/cn";
import type { CalendarEvent } from "@/lib/types";
import { externalHref } from "@/lib/url";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; events: CalendarEvent[] };

type Source = "sonarr" | "radarr";

const ALL_SOURCES: Source[] = ["sonarr", "radarr"];
const PREF_KEY = "calendar_sources";

/** Status drives the colour, matching the old calendar's legend. */
function statusOf(event: CalendarEvent): "on-air" | "unaired" | "unmonitored" {
  if (event.has_file) return "on-air";
  return event.monitored === false ? "unmonitored" : "unaired";
}

const STATUS_DOT: Record<string, string> = {
  "on-air": "bg-success",
  unaired: "bg-warning",
  unmonitored: "bg-muted",
};

function monthBounds(month: Date): { start: string; end: string } {
  const first = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1));
  const last = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 0));
  return {
    start: first.toISOString().slice(0, 10),
    end: last.toISOString().slice(0, 10),
  };
}

function monthLabel(month: Date): string {
  return month.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/**
 * The six-week grid the month is drawn on: whole weeks from the Monday on or
 * before the 1st, so every month renders the same shape.
 */
function gridDays(month: Date): string[] {
  const first = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1));
  const offset = (first.getUTCDay() + 6) % 7; // Monday-first
  const start = new Date(first);
  start.setUTCDate(start.getUTCDate() - offset);
  const days: string[] = [];
  for (let index = 0; index < 42; index += 1) {
    const day = new Date(start);
    day.setUTCDate(day.getUTCDate() + index);
    days.push(day.toISOString().slice(0, 10));
  }
  return days;
}

const WEEKDAY_HEADS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** "Wed 2 Sep" — the agenda's day heading, read in UTC like the grid. */
function dayHeading(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/** A stable key for an entry within its day. */
function eventKey(event: CalendarEvent): string {
  return `${event.source}-${event.instance_id}-${event.title}-${event.subtitle ?? ""}`;
}

/**
 * Where a calendar entry opens: the series or film in the app that manages it.
 *
 * Both routes are taken from the running apps rather than assumed — Sonarr
 * keys a series on its title slug, Radarr keys a movie on its TMDB id — and
 * both ids already travel with the event. An entry whose id is missing, or
 * whose instance has no usable URL, stays plain text rather than becoming a
 * link that goes nowhere.
 */
function eventUrl(event: CalendarEvent): string | undefined {
  const base = externalHref(event.instance_base_url)?.replace(/\/+$/, "");
  if (!base) return undefined;
  if (event.source === "sonarr" && event.title_slug) {
    return `${base}/series/${encodeURIComponent(event.title_slug)}`;
  }
  if (event.source === "radarr" && event.tmdb_id) {
    return `${base}/movie/${encodeURIComponent(String(event.tmdb_id))}`;
  }
  return undefined;
}

/** The title as a link into Sonarr/Radarr when the entry has one, plain text otherwise. */
function EventTitle({ event, className }: { event: CalendarEvent; className?: string }) {
  const href = eventUrl(event);
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("hover:text-accent hover:underline", className)}
    >
      {event.title}
    </a>
  ) : (
    <span className={className}>{event.title}</span>
  );
}

export function CalendarView() {
  // Seeded on the client only: `new Date()` during render would differ between
  // server and client around UTC midnight and trip a hydration mismatch.
  const [month, setMonth] = useState<Date | null>(null);
  const [today, setToday] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[]>(ALL_SOURCES);
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    const now = new Date();
    setMonth(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)));
    // The grid is built in UTC, so today has to be read in UTC too.
    setToday(now.toISOString().slice(0, 10));
  }, []);

  // Restore the saved source selection; a missing or malformed pref means "all".
  //
  // `touched` is what stops the response racing the user: the fetch is slower
  // than a click, so toggling a source off before it returned had the saved
  // value put it straight back. Once anything has been toggled, the restore
  // is stale by definition and is dropped.
  const touched = useRef(false);
  useEffect(() => {
    clientFetch<Record<string, unknown>>("/api/user/preferences")
      .then((prefs) => {
        if (touched.current) return;
        const saved = prefs[PREF_KEY];
        if (Array.isArray(saved)) {
          const valid = saved.filter((value): value is Source =>
            ALL_SOURCES.includes(value as Source),
          );
          // An empty array is a real choice — every source turned off — not a
          // malformed preference, so it is applied rather than ignored. Only
          // a non-array (absent, or written by something else) means "all".
          setSources(valid);
        }
      })
      .catch(() => {
        // A failed preference read must not stop the calendar rendering.
      });
  }, []);

  const shiftMonth = useCallback((delta: number) => {
    setMonth((current) => {
      if (!current) return current;
      return new Date(
        Date.UTC(current.getUTCFullYear(), current.getUTCMonth() + delta, 1),
      );
    });
  }, []);

  function toggleSource(source: Source) {
    touched.current = true;
    const next = sources.includes(source)
      ? sources.filter((value) => value !== source)
      : [...sources, source];
    setSources(next);
    clientFetch(`/api/user/preferences/${PREF_KEY}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: next }),
    }).catch(() => {
      // Persisting is best-effort; the toggle still applies for this visit.
    });
  }

  useEffect(() => {
    if (!month) return;
    const controller = new AbortController();
    const { start, end } = monthBounds(month);
    setState({ status: "loading" });

    clientFetch<CalendarEvent[]>(`/api/calendar?start=${start}&end=${end}`, {
      signal: controller.signal,
    })
      .then((events) => {
        if (!controller.signal.aborted) setState({ status: "ok", events });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Failed to load calendar",
        });
      });

    // Aborting on month change stops a slow response for the previous month
    // from landing after a fast one for the current month.
    return () => controller.abort();
  }, [month]);

  const byDate = useMemo(() => {
    const grouped = new Map<string, CalendarEvent[]>();
    if (state.status !== "ok") return grouped;
    for (const event of state.events) {
      if (!sources.includes(event.source as Source)) continue;
      const list = grouped.get(event.date);
      if (list) list.push(event);
      else grouped.set(event.date, [event]);
    }
    return grouped;
  }, [state, sources]);

  const days = month ? gridDays(month) : [];
  const currentMonth = month ? month.getUTCMonth() : -1;
  const agendaDays = days.filter(
    (day) => Number(day.slice(5, 7)) - 1 === currentMonth && byDate.has(day),
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          aria-label="Previous month"
          onClick={() => shiftMonth(-1)}
        >
          ‹
        </Button>
        <span className="min-w-36 text-center text-sm font-medium">
          {month ? monthLabel(month) : " "}
        </span>
        <Button
          size="sm"
          variant="secondary"
          aria-label="Next month"
          onClick={() => shiftMonth(1)}
        >
          ›
        </Button>

        <fieldset className="ml-auto flex gap-1 border-0 p-0">
          <legend className="sr-only">Show sources</legend>
          {ALL_SOURCES.map((option) => (
            <Button
              key={option}
              size="sm"
              variant={sources.includes(option) ? "primary" : "ghost"}
              aria-pressed={sources.includes(option)}
              onClick={() => toggleSource(option)}
              className="capitalize"
            >
              {option}
            </Button>
          ))}
        </fieldset>
      </div>

      {state.status === "loading" && <Spinner label="Loading calendar…" />}

      {state.status === "error" && (
        <p className="text-sm text-error" role="alert">
          {state.message}
        </p>
      )}

      {/* Below md the month is an agenda: the seven-column grid needs 640px
          and on a phone scrolled sideways with four columns showing and
          every title chopped. Only days with entries are listed. */}
      {state.status === "ok" && month && (
        <div className="md:hidden">
          {agendaDays.length === 0 ? (
            <p className="py-6 text-sm text-muted">
              Nothing scheduled in {monthLabel(month)}.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {agendaDays.map((day) => {
                const isToday = day === today;
                return (
                  <li key={day}>
                    <h3
                      className={cn(
                        "sticky top-0 rounded-sm bg-surface-2 px-2 py-1.5 text-sm font-semibold",
                        isToday && "text-accent",
                      )}
                    >
                      {dayHeading(day)}
                      {isToday && (
                        <span className="ml-2 text-xs font-normal text-muted">Today</span>
                      )}
                    </h3>
                    <ul className="divide-y divide-border">
                      {(byDate.get(day) ?? []).map((event) => (
                        <li
                          key={eventKey(event)}
                          className="flex items-start gap-2 px-2 py-2"
                        >
                          <span
                            aria-hidden="true"
                            className={cn(
                              "mt-1.5 size-2 shrink-0 rounded-full",
                              STATUS_DOT[statusOf(event)],
                            )}
                          />
                          <span className="min-w-0 flex-1">
                            <EventTitle event={event} className="block text-sm" />
                            {event.subtitle && (
                              <span className="block text-xs text-muted">
                                {event.subtitle}
                              </span>
                            )}
                          </span>
                          <span className="shrink-0 text-xs text-muted capitalize">
                            {event.source}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {state.status === "ok" && month && (
        <div className="hidden overflow-x-auto md:block">
          <div className="grid min-w-160 grid-cols-7 gap-px rounded-lg border border-border bg-border">
            {WEEKDAY_HEADS.map((head) => (
              <div
                key={head}
                className="bg-surface px-2 py-1 text-center text-xs font-medium text-muted"
              >
                {head}
              </div>
            ))}

            {days.map((day) => {
              const events = byDate.get(day) ?? [];
              const outside = Number(day.slice(5, 7)) - 1 !== currentMonth;
              const isToday = day === today;
              return (
                <div
                  key={day}
                  aria-current={isToday ? "date" : undefined}
                  className={cn(
                    "min-h-24 bg-surface p-1 align-top",
                    outside && "opacity-40",
                    isToday && "ring-1 ring-accent ring-inset",
                  )}
                >
                  <div
                    className={cn(
                      "mb-1 text-right text-xs tabular-nums",
                      isToday ? "font-semibold text-accent" : "text-muted",
                    )}
                  >
                    {Number(day.slice(8, 10))}
                  </div>
                  <ul className="flex flex-col gap-0.5">
                    {events.map((event) => (
                      <li
                        key={eventKey(event)}
                        className="flex items-center gap-1"
                        title={`${event.title}${event.subtitle ? ` — ${event.subtitle}` : ""}`}
                      >
                        <span
                          aria-hidden="true"
                          className={cn(
                            "size-1.5 shrink-0 rounded-full",
                            STATUS_DOT[statusOf(event)],
                          )}
                        />
                        <EventTitle event={event} className="truncate text-[11px]" />
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <ul className="flex flex-wrap gap-4 text-xs text-muted">
        {(
          [
            ["on-air", "On air"],
            ["unaired", "Unaired"],
            ["unmonitored", "Unmonitored"],
          ] as const
        ).map(([status, label]) => (
          <li key={status} className="flex items-center gap-1">
            <span
              aria-hidden="true"
              className={cn("size-2 rounded-full", STATUS_DOT[status])}
            />
            {label}
          </li>
        ))}
      </ul>
    </div>
  );
}
