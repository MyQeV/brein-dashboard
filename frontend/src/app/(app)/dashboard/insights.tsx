"use client";

import { useState } from "react";
import { RankedBars } from "@/components/charts/ranked-bars";
import { StatTile } from "@/components/charts/stat-tile";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { formatCount, formatDateTime } from "@/lib/format";
import { type ApiRow, rowNumber, rowText } from "@/lib/rows";
import { useApi } from "@/lib/use-api";

type Concurrency = {
  per_day: { date: string; peak: number }[];
  peak: number;
  peak_date: string;
};

type IdleUser = {
  instance_id: number;
  instance_label: string;
  display_name: string;
  last_played: string;
  last_activity_date: string;
};

const IDLE_DAYS = 30;
const IDLE_PREVIEW = 5;

/**
 * Peak simultaneous streams.
 *
 * Total watch time says how much was watched; this says how much was watched
 * *at once*, which is the number that tells you whether the server is sized
 * right. A stat tile with the per-day peaks as its trend — it used to be a
 * one-bar bar chart on a single-day range. Computed from session overlap;
 * see brein/store/dashboard_insights.py.
 */
export function ConcurrencyTile({ query }: { query: string }) {
  const state = useApi<Concurrency>(`/api/dashboard/concurrency${query}`);

  if (state.status === "error") {
    return <StatTile label="Peak concurrent" value="—" hint={state.message} />;
  }
  if (state.status !== "ok") {
    return <StatTile label="Peak concurrent" value="…" />;
  }
  return (
    <StatTile
      label="Peak concurrent"
      value={formatCount(state.data.peak)}
      hint={state.data.peak_date ? `on ${state.data.peak_date}` : undefined}
      sparkline={
        state.data.per_day.length > 1
          ? state.data.per_day.map((row) => row.peak)
          : undefined
      }
    />
  );
}

/**
 * The titles played most often.
 *
 * `most_watched_items` ranks by play count rather than hours, so it surfaces
 * rewatches and short content that the watch-time lists bury.
 */
export function MostPlayedCard({ rows }: { rows: ApiRow[] }) {
  const items = rows
    .map((row, index) => ({
      id: `${rowText(row, ["instance_id"], "")}:${rowText(row, ["item_id"], String(index))}`,
      label: rowText(row),
      value: rowNumber(row, ["plays"]),
    }))
    .filter((row) => row.label);

  return (
    <Card title="Most played">
      <RankedBars
        data={items}
        format={(value) => `${value} play${value === 1 ? "" : "s"}`}
        emptyLabel="No playback recorded for this range."
      />
    </Card>
  );
}

/** Accounts that have not played anything for a month, or ever. */
export function IdleUsersCard({ instanceIds }: { instanceIds?: string }) {
  // Scoped like every other card: picking one server used to narrow the whole
  // page except this list.
  const scope = instanceIds ? `&instance_ids=${encodeURIComponent(instanceIds)}` : "";
  const state = useApi<{ users: IdleUser[] }>(
    `/api/dashboard/idle-users?days=${IDLE_DAYS}${scope}`,
  );
  const [showAll, setShowAll] = useState(false);

  const users = state.status === "ok" ? state.data.users : [];
  const shown = showAll ? users : users.slice(0, IDLE_PREVIEW);
  const hidden = users.length - shown.length;

  return (
    <Card
      title="Idle users"
      actions={
        state.status === "ok" && users.length > 0 ? (
          <span className="text-xs text-muted">
            <span className="text-text tabular-nums">{formatCount(users.length)}</span>{" "}
            nothing played in {IDLE_DAYS} days
          </span>
        ) : undefined
      }
    >
      {state.status === "loading" && <Spinner label="Loading…" />}
      {state.status === "error" && (
        <p className="text-sm text-error" role="alert">
          {state.message}
        </p>
      )}
      {state.status === "ok" && users.length === 0 && (
        <p className="text-sm text-muted">Everyone has watched something recently.</p>
      )}
      {state.status === "ok" && users.length > 0 && (
        <div className="flex flex-col gap-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-muted">
                <th className="pb-1 font-medium">User</th>
                <th className="w-24 pb-1 font-medium">Server</th>
                <th className="w-28 pb-1 font-medium">Last played</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {shown.map((user) => (
                <tr key={`${user.instance_id}-${user.display_name}`}>
                  <td className="py-1.5">{user.display_name}</td>
                  <td className="py-1.5 text-muted">{user.instance_label || "—"}</td>
                  <td className="py-1.5 whitespace-nowrap text-muted tabular-nums">
                    {user.last_played ? formatDateTime(user.last_played) : "Never"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {hidden > 0 ? (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="self-start text-xs text-muted hover:text-text"
            >
              +{hidden} more · <span className="text-accent">show all</span>
            </button>
          ) : showAll && users.length > IDLE_PREVIEW ? (
            <button
              type="button"
              onClick={() => setShowAll(false)}
              className="self-start text-xs text-accent hover:text-text"
            >
              show fewer
            </button>
          ) : null}
        </div>
      )}
    </Card>
  );
}
