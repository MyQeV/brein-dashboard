"use client";

import { Fragment, type ReactNode, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { formatCount, formatDuration } from "@/lib/format";

/**
 * Sessions grouped by the day they happened on.
 *
 * Shared by the Average-session breakdown and the weekday drill, which ask the
 * same question of different slices: what was watched, by whom, on each day.
 */

export type SessionRow = {
  user_display_name?: string;
  title?: string;
  item_type?: string;
  series_name?: string;
  season_number?: number | null;
  episode_number?: number | null;
  instance_label?: string;
  /** Which media backend the row came from; set by the API's session routes. */
  backend?: string;
  played_at?: string;
  duration_seconds?: number;
};

/** "Breaking Bad – Ozymandias (S05E14)" for episodes, the plain title otherwise. */
export function sessionTitle(row: SessionRow): string {
  const title = row.title || "Unknown";
  if (!row.series_name) return title;
  const season = row.season_number;
  const episode = row.episode_number;
  const numbering =
    typeof season === "number" && typeof episode === "number"
      ? ` (S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")})`
      : "";
  return `${row.series_name} – ${title}${numbering}`;
}

/** The calendar day a session belongs to, read in the app's zone. */
export function sessionDay(row: SessionRow, timeZone: string): string {
  if (!row.played_at) return "—";
  const parsed = new Date(row.played_at);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleDateString("en-CA", { timeZone });
}

export function sessionTime(row: SessionRow, timeZone: string): string {
  if (!row.played_at) return "—";
  const parsed = new Date(row.played_at);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleTimeString("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * "Thursday" for a YYYY-MM-DD date.
 *
 * The date is already resolved in the app's zone, so it is read back at UTC
 * noon — parsing a bare date at midnight lands on the previous day west of
 * Greenwich and names the wrong weekday.
 */
export function weekdayName(day: string): string {
  const parsed = new Date(`${day}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("en-GB", { weekday: "long", timeZone: "UTC" });
}

/**
 * Whether the API truncated the list.
 *
 * The session endpoints run one query per media backend, each with its own
 * LIMIT, and concatenate. So `rows.length >= limit` over-reports — three
 * hundred Emby plus three hundred Plex sessions announced "showing the most
 * recent 600" over a complete list of six hundred — and counting per
 * *instance* under-reports, because one capped arm is split across the labels
 * of the instances inside it, which is worse: it presents a truncated list as
 * the whole of it.
 *
 * The router stamps each row with the arm it came from, which is the thing
 * the limit was applied to. A row without one is counted under "", so an
 * older response still behaves like the plain length check.
 */
export function isCapped(rows: SessionRow[], limit: number): boolean {
  const perBackend = new Map<string, number>();
  for (const row of rows) {
    const key = typeof row.backend === "string" ? row.backend : "";
    perBackend.set(key, (perBackend.get(key) ?? 0) + 1);
  }
  for (const count of perBackend.values()) {
    if (count >= limit) return true;
  }
  return false;
}

export function groupByDay(
  rows: SessionRow[],
  timeZone: string,
): { day: string; rows: SessionRow[] }[] {
  const byDay = new Map<string, SessionRow[]>();
  for (const row of rows) {
    const day = sessionDay(row, timeZone);
    const list = byDay.get(day);
    if (list) list.push(row);
    else byDay.set(day, [row]);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([day, dayRows]) => ({ day, rows: dayRows }));
}

export function Chevron({
  open,
  onToggle,
  label,
}: {
  open: boolean;
  /** Given, the chevron is the row's keyboard-reachable control. */
  onToggle?: () => void;
  label?: string;
}) {
  const glyph = (
    <span aria-hidden="true" className="pr-1 text-muted">
      {open ? "▾" : "▸"}
    </span>
  );
  if (!onToggle) return glyph;
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={label}
      onClick={(event) => {
        // The row handles the click too; without this it would toggle twice.
        event.stopPropagation();
        onToggle();
      }}
      className="cursor-pointer"
    >
      {glyph}
    </button>
  );
}

/**
 * A summary row that expands.
 *
 * The cells are real `<td>`s rather than a grid inside one spanning cell:
 * a grid lays itself out independently of the table, so its columns drifted
 * out of line with the header above them.
 */
export function ExpandRow({
  open,
  onToggle,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  // The row stays a row: role="button" on a <tr> takes its cells out of the
  // accessibility tree, so the whole thing is announced as one run of text
  // with no column association. The keyboard path is the button inside the
  // first cell (see Chevron's use in the callers); clicking the row is a
  // mouse convenience on top of it.
  return (
    <tr
      onClick={onToggle}
      className={cn("cursor-pointer hover:bg-surface-2", open && "bg-surface-2")}
    >
      {children}
    </tr>
  );
}

/** The session lines themselves: what was watched, of what type, for how long. */
export function SessionList({
  rows,
  timeZone,
  showUser = false,
}: {
  rows: SessionRow[];
  timeZone: string;
  showUser?: boolean;
}) {
  if (rows.length === 0) {
    return <p className="py-2 text-xs text-muted">No sessions.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted">
            {showUser && <th className="w-28 py-1 pr-2 font-normal">User</th>}
            <th className="py-1 pr-2 font-normal">Item</th>
            <th className="w-20 py-1 pr-2 font-normal">Type</th>
            <th className="w-28 py-1 pr-2 font-normal">Server</th>
            <th className="w-14 py-1 pr-2 font-normal">Time</th>
            <th className="w-16 py-1 text-right font-normal">Duration</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {rows.map((row, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: sessions carry no id; played_at can repeat
            <tr key={`${row.played_at ?? ""}-${index}`}>
              {showUser && (
                <td className="w-28 py-1 pr-2 align-top">{row.user_display_name}</td>
              )}
              <td className="py-1 pr-2">{sessionTitle(row)}</td>
              <td className="w-20 py-1 pr-2 text-muted">{row.item_type || "—"}</td>
              <td className="w-28 py-1 pr-2 truncate text-muted">
                {row.instance_label || "—"}
              </td>
              <td className="w-14 py-1 pr-2 whitespace-nowrap text-muted">
                {sessionTime(row, timeZone)}
              </td>
              <td className="w-16 py-1 text-right tabular-nums">
                {formatDuration(row.duration_seconds ?? 0)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-border font-medium">
            <td colSpan={showUser ? 5 : 4} className="py-1 pr-2 text-muted">
              Total
            </td>
            <td className="py-1 text-right tabular-nums">
              {formatDuration(
                rows.reduce((sum, row) => sum + (row.duration_seconds ?? 0), 0),
              )}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** Day headings only earn their space when the range covers more than one. */
export function SessionBody({
  rows,
  timeZone,
  multiDay,
  showUser = false,
}: {
  rows: SessionRow[];
  timeZone: string;
  multiDay: boolean;
  showUser?: boolean;
}) {
  if (!multiDay)
    return <SessionList rows={rows} timeZone={timeZone} showUser={showUser} />;

  return (
    <div className="flex flex-col gap-2">
      {groupByDay(rows, timeZone).map((group) => (
        <div key={group.day}>
          {/* The day's total is the table's own footer now, under Duration. */}
          <p className="pb-0.5 text-xs font-medium text-muted">
            {weekdayName(group.day)} {group.day}
          </p>
          <SessionList rows={group.rows} timeZone={timeZone} showUser={showUser} />
        </div>
      ))}
    </div>
  );
}

/** The Day / Date / Sessions / Total / Average table, expandable per day. */
export function SessionsByDayTable({
  rows,
  timeZone,
  showUser = true,
  capped = false,
  defaultExpanded = false,
}: {
  rows: SessionRow[];
  timeZone: string;
  /** A per-user drill repeats the dialog's own title on every row. */
  showUser?: boolean;
  /** The API returned its maximum, so these are the newest, not all of them. */
  capped?: boolean;
  /** Every day starts open — the "modal lists" profile preference. */
  defaultExpanded?: boolean;
}) {
  // The days the user has flipped away from the default, not the open ones:
  // that way "everything open" costs nothing at mount, and a preference that
  // arrives a moment after the first render simply flips the untouched days.
  const [flipped, setFlipped] = useState<ReadonlySet<string>>(new Set());
  // Memoised on the rows, not on `flipped`: a drill can hold 500 sessions,
  // and each one costs an Intl date format to bucket. Without this, opening a
  // day re-bucketed the whole list.
  const days = useMemo(() => groupByDay(rows, timeZone), [rows, timeZone]);

  function toggle(key: string) {
    setFlipped((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  if (days.length === 0) {
    return <p className="text-sm text-muted">No sessions in this range.</p>;
  }

  return (
    <>
      {capped && (
        <p className="pb-2 text-xs text-muted">
          Showing the most recent {formatCount(rows.length)} sessions — the totals below
          cover those, not the whole range.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="w-28 py-1 font-normal">Day</th>
              <th className="py-1 font-normal">Date</th>
              <th className="w-24 py-1 text-right font-normal">Sessions</th>
              <th className="w-24 py-1 text-right font-normal">Total</th>
              <th className="w-24 py-1 text-right font-normal">Average</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {days.map((group) => {
              const total = group.rows.reduce(
                (sum, row) => sum + (row.duration_seconds ?? 0),
                0,
              );
              const open = flipped.has(group.day) !== defaultExpanded;
              return (
                <Fragment key={group.day}>
                  <ExpandRow open={open} onToggle={() => toggle(group.day)}>
                    <td className="w-28 whitespace-nowrap py-1">
                      <Chevron
                        open={open}
                        onToggle={() => toggle(group.day)}
                        label={`Sessions on ${group.day}`}
                      />
                      {weekdayName(group.day)}
                    </td>
                    <td className="whitespace-nowrap py-1 tabular-nums">{group.day}</td>
                    <td className="whitespace-nowrap py-1 text-right tabular-nums">
                      {formatCount(group.rows.length)}
                    </td>
                    <td className="whitespace-nowrap py-1 text-right tabular-nums">
                      {formatDuration(total)}
                    </td>
                    <td className="whitespace-nowrap py-1 text-right tabular-nums">
                      {formatDuration(Math.round(total / group.rows.length))}
                    </td>
                  </ExpandRow>
                  {open && (
                    <tr>
                      <td colSpan={5} className="bg-bg/60 px-3 pb-3">
                        <SessionList
                          rows={group.rows}
                          timeZone={timeZone}
                          showUser={showUser}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
