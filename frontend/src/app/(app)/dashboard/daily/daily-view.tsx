"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { OTHER_COLOR, rankColor } from "@/components/charts/chart-theme";
import { ChartTooltip } from "@/components/charts/chart-tooltip";
import {
  type Stack,
  StackedColumns,
  type StackSegment,
} from "@/components/charts/stacked-columns";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { BELOW_LG } from "@/lib/breakpoints";
import { clientFetch } from "@/lib/client-fetch";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDuration } from "@/lib/format";
import { rowNumber, rowText } from "@/lib/rows";
import type { MediaMetrics, UserSessionRow } from "@/lib/types";

type Row = { date: string; userKey: string; userName: string; seconds: number };

/**
 * The plot area's height, sized from its own width the way the old chart's
 * `maintainAspectRatio` did, then clamped so it stays usable on a narrow
 * window and does not run off a tall one. Segment heights are computed in
 * pixels, so the measured value drives them.
 */
const PLOT_ASPECT = 3.4;
const PLOT_MIN_PX = 220;
const PLOT_MAX_PX = 460;
const PLOT_FALLBACK_PX = 300;

/** Below this per-column budget (column + gap) the flexible layout is unusable. */
const MIN_COLUMN_PX = 14;
/** Width a day label needs before its neighbours start overlapping. */
const LABEL_PX = 40;

const DAY_NAMES = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function dayLabel(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  return `${DAY_NAMES[value.getUTCDay()]} ${date.slice(5)}`;
}

type Detail =
  | { status: "idle" }
  | { status: "loading"; date: string; userKey: string; userName: string }
  | { status: "error"; message: string }
  | {
      status: "ok";
      date: string;
      userKey: string;
      userName: string;
      rows: UserSessionRow[];
    };

/**
 * Rows come from `watch_time_per_user_per_day`
 * (brein/store/metrics_activity.py & plex_dashboard_metrics.py, merged in
 * brein/web/routers/dashboard.py): `{ date, instance_id, user_id,
 * display_name, total_seconds }`. `user_id` is a bare per-instance id, so the
 * key sent to `/api/dashboard/user-sessions` must be the compound
 * "instance_id:user_id" form `_user_instance_filter`
 * (brein/store/metrics_helpers.py) expects — a bare id is silently ignored.
 */
function normalise(rows: unknown[]): Row[] {
  const out: Row[] = [];
  for (const entry of rows) {
    if (!entry || typeof entry !== "object") continue;
    const row = entry as Record<string, unknown>;
    const date = typeof row.date === "string" ? row.date : "";
    const instanceId = row.instance_id;
    const userId = row.user_id;
    const hasInstanceId =
      typeof instanceId === "number" || typeof instanceId === "string";
    const hasUserId =
      (typeof userId === "string" || typeof userId === "number") && String(userId) !== "";
    if (!date || !hasInstanceId || !hasUserId) continue;

    const displayName = row.display_name;
    const userName = row.user_name;
    const name =
      (typeof displayName === "string" && displayName) ||
      (typeof userName === "string" && userName) ||
      String(userId);

    out.push({
      date,
      userKey: `${instanceId}:${userId}`,
      userName: name,
      seconds: typeof row.total_seconds === "number" ? row.total_seconds : 0,
    });
  }
  return out;
}

export function DailyView({ metrics }: { metrics: MediaMetrics }) {
  const rows = useMemo(() => normalise(metrics.watch_time_per_user_per_day), [metrics]);
  const [detail, setDetail] = useState<Detail>({ status: "idle" });
  const latestRequest = useRef<string>("");
  // Card renders a <section> but does not forward refs, so the "What was
  // watched" panel is wrapped in a plain div to get a scroll target.
  const panelRef = useRef<HTMLDivElement | null>(null);

  /**
   * One stacked column per day, a segment per user — the shape the old chart
   * had, where clicking a user's segment opened what they watched that day.
   */
  const { stacks, legend, maxTotal } = useMemo(() => {
    const totalsByUser = new Map<string, { name: string; seconds: number }>();
    for (const row of rows) {
      const current = totalsByUser.get(row.userKey);
      if (current) current.seconds += row.seconds;
      else totalsByUser.set(row.userKey, { name: row.userName, seconds: row.seconds });
    }

    // Colours follow overall rank, so a user keeps one colour across every
    // day. The top eight take the theme's validated slots; everyone after
    // that gets a generated hue of their own — one grey for the tail left a
    // server with thirty viewers showing mostly identical bands.
    const ranked = [...totalsByUser.entries()].sort(
      ([, a], [, b]) => b.seconds - a.seconds,
    );
    const colorByUser = new Map<string, string>();
    ranked.forEach(([key], index) => {
      colorByUser.set(key, rankColor(index));
    });

    const byDay = new Map<string, Row[]>();
    for (const row of rows) {
      const list = byDay.get(row.date);
      if (list) list.push(row);
      else byDay.set(row.date, [row]);
    }

    const stacks = [...byDay.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, dayRows]) => {
        const segments: StackSegment[] = [...dayRows]
          .sort((a, b) => b.seconds - a.seconds)
          .map((row) => ({
            key: row.userKey,
            name: row.userName,
            seconds: row.seconds,
            color: colorByUser.get(row.userKey) ?? OTHER_COLOR,
          }));
        return {
          date,
          total: segments.reduce((sum, segment) => sum + segment.seconds, 0),
          segments,
        } satisfies Stack;
      });

    const legend = ranked.map(([key, value], index) => ({
      key,
      name: value.name,
      color: rankColor(index),
    }));

    return {
      stacks,
      legend,
      maxTotal: Math.max(0, ...stacks.map((stack) => stack.total)),
    };
  }, [rows]);

  const perUserDay = useMemo(
    () => [...rows].sort((a, b) => b.seconds - a.seconds).slice(0, 25),
    [rows],
  );

  // Hidden users are dropped from the columns and the bars rescale to what is
  // left, the way toggling a Chart.js legend entry behaved.
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());

  const visible = useMemo(() => {
    if (hidden.size === 0) return { stacks, maxTotal };
    // Recompute each stack's total from the segments that remain: the
    // floating "tallest day" label in StackedColumns reads `stack.total`
    // directly, so a stale, unfiltered total would keep showing a value the
    // visible segments no longer add up to once a user is hidden.
    const shown: Stack[] = stacks.map((stack) => {
      const segments = stack.segments.filter((segment) => !hidden.has(segment.key));
      return {
        ...stack,
        segments,
        total: segments.reduce((sum, segment) => sum + segment.seconds, 0),
      };
    });
    return {
      stacks: shown,
      maxTotal: Math.max(0, ...shown.map((stack) => stack.total)),
    };
  }, [stacks, maxTotal, hidden]);

  function toggleUser(key: string) {
    setHidden((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  // Measured rather than assumed: the card is wider on a desktop than in a
  // split window, and the bars should use whatever room it actually has.
  const plotRef = useRef<HTMLDivElement | null>(null);
  // A tooltip of our own: the native title attribute waits a second before it
  // appears, which is no use when scrubbing across a stack of fifty bands.
  const [hover, setHover] = useState<{
    text: string;
    sub: string;
    x: number;
    y: number;
  } | null>(null);
  const [plotHeight, setPlotHeight] = useState<number>(PLOT_FALLBACK_PX);
  const [plotWidth, setPlotWidth] = useState<number>(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-attach when the plot appears or vanishes (see comment)
  useEffect(() => {
    // Depends on whether the plot is rendered at all: with an empty first
    // range the ref was null, the observer never attached, and the height
    // stayed at its fallback for the life of the component — including after
    // navigating to a range that does have data.
    const node = plotRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width;
      if (width > 0) {
        setPlotWidth(width);
        setPlotHeight(
          Math.round(Math.min(PLOT_MAX_PX, Math.max(PLOT_MIN_PX, width / PLOT_ASPECT))),
        );
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [stacks.length]);

  // Width-aware, not count-aware: thirty days fit a desktop but not a phone.
  const dense = plotWidth > 0 && stacks.length * MIN_COLUMN_PX > plotWidth;
  const labelStride = Math.max(
    1,
    Math.ceil(stacks.length / Math.max(1, Math.floor((plotWidth || 1200) / LABEL_PX))),
  );

  function loadDetail(row: Row) {
    const requestKey = `${row.userKey}|${row.date}`;
    latestRequest.current = requestKey;
    setDetail({
      status: "loading",
      date: row.date,
      userKey: row.userKey,
      userName: row.userName,
    });
    // On a phone the panel sits below the chart; bring it up when a pick is made.
    if (window.matchMedia(BELOW_LG).matches) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      panelRef.current?.scrollIntoView({
        behavior: reduce ? "auto" : "smooth",
        block: "start",
      });
    }
    clientFetch<UserSessionRow[]>(
      `/api/dashboard/user-sessions?user_id=${encodeURIComponent(row.userKey)}&date=${row.date}`,
    )
      .then((sessions) => {
        // A slower response for a previously clicked row must not overwrite
        // the row the user actually has selected now.
        if (latestRequest.current !== requestKey) return;
        setDetail({
          status: "ok",
          date: row.date,
          userKey: row.userKey,
          userName: row.userName,
          rows: sessions,
        });
      })
      .catch((error: unknown) => {
        if (latestRequest.current !== requestKey) return;
        setDetail({
          status: "error",
          message: error instanceof Error ? error.message : "Failed to load sessions",
        });
      });
  }

  function loadSegment(date: string, segment: StackSegment) {
    loadDetail({
      date,
      userKey: segment.key,
      userName: segment.name,
      seconds: segment.seconds,
    });
  }

  const selected =
    "userKey" in detail ? { key: detail.userKey, date: detail.date } : null;
  const totalSeconds = stacks.reduce((sum, stack) => sum + stack.total, 0);

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Watch time per user, per day"
        actions={
          stacks.length > 0 ? (
            <span className="text-xs text-muted">
              <span className="text-text tabular-nums">
                {formatDuration(totalSeconds)}
              </span>{" "}
              · {legend.length} {legend.length === 1 ? "user" : "users"}
              <span className="hidden sm:inline">
                {" "}
                · click a segment to see what was watched
              </span>
            </span>
          ) : undefined
        }
      >
        {stacks.length === 0 ? (
          <p className="py-6 text-sm text-muted">No playback recorded for this range.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {/* The tooltip sits outside the scrolling box: inside it, it
                scrolled away from the cursor and was clipped by the overflow
                the dense layout needs. */}
            {/* biome-ignore lint/a11y/noStaticElementInteractions: mouse-leave only clears the tooltip; the segments are buttons */}
            <div className="relative pt-5" onMouseLeave={() => setHover(null)}>
              {hover && (
                <ChartTooltip
                  x={hover.x}
                  y={hover.y + 20}
                  value={hover.text}
                  label={hover.sub}
                />
              )}
              <StackedColumns
                stacks={visible.stacks}
                maxTotal={visible.maxTotal}
                plotHeight={plotHeight}
                dense={dense}
                labelStride={labelStride}
                plotRef={plotRef}
                selected={selected}
                dayLabel={dayLabel}
                onSegmentClick={loadSegment}
                onHover={setHover}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
              <ul className="flex flex-wrap gap-1.5">
                {legend.map((entry) => {
                  const off = hidden.has(entry.key);
                  return (
                    <li key={entry.key}>
                      <button
                        type="button"
                        aria-pressed={!off}
                        onClick={() => toggleUser(entry.key)}
                        className={cn(
                          "flex cursor-pointer items-center gap-1.5 rounded-full bg-surface-2 px-2 py-1 text-xs",
                          off ? "text-muted line-through" : "text-text",
                        )}
                      >
                        <span
                          aria-hidden="true"
                          className={cn("size-2 rounded-full", off && "opacity-40")}
                          style={{ background: entry.color }}
                        />
                        {entry.name}
                      </button>
                    </li>
                  );
                })}
              </ul>
              <fieldset className="flex gap-1 border-0 p-0">
                <legend className="sr-only">Show users</legend>
                <Button size="sm" variant="ghost" onClick={() => setHidden(new Set())}>
                  All
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setHidden(new Set(legend.map((entry) => entry.key)))}
                >
                  None
                </Button>
              </fieldset>
            </div>
          </div>
        )}
      </Card>

      {/* The per-user list is three short columns and needs no more than
          26rem; the titles on the right are what run long, so they get the
          rest of the row. */}
      <div className="grid gap-4 lg:grid-cols-[26rem_minmax(0,1fr)]">
        <Card
          title="Per user, per day"
          actions={
            rows.length > perUserDay.length ? (
              <span className="text-xs text-muted">
                top {perUserDay.length} of {rows.length}
              </span>
            ) : undefined
          }
        >
          {perUserDay.length === 0 ? (
            <p className="py-4 text-sm text-muted">
              No playback recorded for this range.
            </p>
          ) : (
            <ul className="max-h-[32rem] overflow-y-auto text-sm">
              {perUserDay.map((row) => {
                // Compared by key, not display name: two accounts can share a
                // name, and both rows would then highlight for one fetch.
                const isSelected =
                  selected?.key === row.userKey && selected.date === row.date;
                const color =
                  legend.find((entry) => entry.key === row.userKey)?.color ?? OTHER_COLOR;
                return (
                  <li key={`${row.date}-${row.userKey}`}>
                    <button
                      type="button"
                      onClick={() => loadDetail(row)}
                      className={cn(
                        "grid w-full grid-cols-[4rem_0.5rem_minmax(0,1fr)_auto] items-center gap-2.5 rounded-sm px-2 py-1.5 text-left hover:bg-surface-2",
                        isSelected && "bg-surface-2",
                      )}
                    >
                      <span className="tabular-nums text-muted">
                        {dayLabel(row.date)}
                      </span>
                      <span
                        aria-hidden="true"
                        className="size-2 rounded-full"
                        style={{ background: color }}
                      />
                      <span className="truncate">{row.userName}</span>
                      <span className="tabular-nums text-muted">
                        {formatDuration(row.seconds)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <div ref={panelRef} className="flex flex-col">
          <Card title="What was watched" className="flex-1">
            {detail.status === "idle" && (
              <p className="py-4 text-sm text-muted">
                Pick a segment or a row to see what was watched.
              </p>
            )}
            {detail.status === "loading" && <Spinner label="Loading sessions…" />}
            {detail.status === "error" && (
              <p className="text-sm text-error" role="alert">
                {detail.message}
              </p>
            )}
            {(detail.status === "ok" || detail.status === "loading") && (
              <div className="flex flex-col gap-0.5 pb-3">
                <span className="flex items-center gap-2 text-base font-semibold">
                  <span
                    aria-hidden="true"
                    className="size-2.5 rounded-full"
                    style={{
                      background:
                        legend.find((entry) => entry.key === detail.userKey)?.color ??
                        OTHER_COLOR,
                    }}
                  />
                  {detail.userName} · {dayLabel(detail.date)}
                </span>
                {detail.status === "ok" && (
                  <span className="text-xs text-muted">
                    <span className="text-text tabular-nums">
                      {detail.rows.length}{" "}
                      {detail.rows.length === 1 ? "session" : "sessions"} ·{" "}
                      {formatDuration(
                        detail.rows.reduce(
                          (sum, session) =>
                            sum +
                            rowNumber(session as Record<string, unknown>, [
                              "duration_seconds",
                            ]),
                          0,
                        ),
                      )}
                    </span>
                  </span>
                )}
              </div>
            )}
            {detail.status === "ok" && detail.rows.length === 0 && (
              <p className="py-4 text-sm text-muted">No sessions recorded that day.</p>
            )}
            {detail.status === "ok" && detail.rows.length > 0 && (
              <ul className="max-h-[32rem] divide-y divide-border overflow-y-auto text-sm">
                {detail.rows.map((session, index) => {
                  const row = session as Record<string, unknown>;
                  return (
                    <li
                      // biome-ignore lint/suspicious/noArrayIndexKey: sessions carry no id; played_at can repeat
                      key={`${row.played_at}-${index}`}
                      className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-baseline gap-2.5 py-2"
                    >
                      <span className="tabular-nums text-muted">
                        {formatDateTime(row.played_at, metrics.app_timezone).slice(-5)}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate">
                          {rowText(row, ["title"], "—")}
                        </span>
                        <span className="block text-[11px] text-muted">
                          {rowText(row, ["item_type"], "")}
                        </span>
                      </span>
                      <span className="tabular-nums text-muted">
                        {formatDuration(rowNumber(row, ["duration_seconds"]))}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
