"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Chevron,
  ExpandRow,
  isCapped,
  SessionBody,
  type SessionRow,
  SessionsByDayTable,
} from "@/components/sessions-by-day";
import { Modal } from "@/components/ui/modal";
import { Spinner } from "@/components/ui/spinner";
import { BELOW_LG } from "@/lib/breakpoints";
import { clientFetch } from "@/lib/client-fetch";
import { cn } from "@/lib/cn";
import { formatCount, formatDuration } from "@/lib/format";
import { rowNumber, rowText } from "@/lib/rows";
import type { MediaMetrics } from "@/lib/types";
import { useMediaQuery } from "@/lib/use-media-query";
import { MODAL_LISTS_EXPANDED, useBooleanPreference } from "@/lib/use-preference";

/**
 * Which headline number was clicked. Plays, watch time and active users are
 * three readings of one table, so they open the same view.
 */
export type KpiTarget = "users" | "avg-session";

/**
 * Per backend, newest first. The endpoint capped at 500 with no way to ask for
 * more, so a wide range showed its newest slice while the day totals beneath
 * read as though they covered everything.
 */
const SESSION_LIMIT = 2000;

type UserRow = {
  key: string;
  name: string;
  server: string;
  plays: number;
  seconds: number;
};

type Fetched =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; rows: SessionRow[] };

export function KpiModal({
  target,
  metrics,
  query,
  onClose,
}: {
  target: KpiTarget;
  metrics: MediaMetrics;
  query: string;
  onClose: () => void;
}) {
  const timeZone = metrics.app_timezone || "UTC";
  const listsExpanded = useBooleanPreference(MODAL_LISTS_EXPANDED);
  const compact = useMediaQuery(BELOW_LG);
  const multiDay = metrics.start_date !== metrics.end_date;

  // A set, not one key: opening a row must not close the ones already open.
  // It holds the rows flipped away from the preference's default, so "all
  // open" is the empty set and a preference that lands after the first paint
  // flips every untouched row.
  const [flipped, setFlipped] = useState<ReadonlySet<string>>(new Set());
  const isOpen = (key: string) => flipped.has(key) !== listsExpanded;

  function toggle(key: string) {
    setFlipped((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }
  const [userSessions, setUserSessions] = useState<Record<string, Fetched>>({});
  const [allSessions, setAllSessions] = useState<Fetched>({ status: "loading" });

  /** Plays and watch time are separate API lists; this is the join on user. */
  const users = useMemo<UserRow[]>(() => {
    const byKey = new Map<string, UserRow>();
    const keyOf = (row: Record<string, unknown>) =>
      `${rowText(row, ["instance_id"])}:${rowText(row, ["user_id"])}`;

    for (const row of metrics.watch_time_per_user) {
      byKey.set(keyOf(row), {
        key: keyOf(row),
        name: rowText(row, ["display_name", "user_name", "user_id"]) || "Unknown",
        server: rowText(row, ["instance_label"]),
        plays: 0,
        seconds: rowNumber(row, ["total_seconds"]),
      });
    }
    for (const row of metrics.plays_per_user) {
      const key = keyOf(row);
      const existing = byKey.get(key);
      if (existing) existing.plays = rowNumber(row, ["plays"]);
      else
        byKey.set(key, {
          key,
          name: rowText(row, ["display_name", "user_name", "user_id"]) || "Unknown",
          server: rowText(row, ["instance_label"]),
          plays: rowNumber(row, ["plays"]),
          seconds: 0,
        });
    }
    return [...byKey.values()].sort((a, b) => b.seconds - a.seconds);
  }, [metrics]);

  // The sessions-by-day view needs every session; the per-user view fetches
  // one user at a time, on expand.
  useEffect(() => {
    if (target !== "avg-session") return;
    const controller = new AbortController();
    setAllSessions({ status: "loading" });
    const separator = query.startsWith("?") ? "&" : "?";
    clientFetch<SessionRow[]>(
      `/api/dashboard/sessions${query}${separator}limit=${SESSION_LIMIT}`,
      { signal: controller.signal },
    )
      .then((rows) => {
        if (!controller.signal.aborted) setAllSessions({ status: "ok", rows });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setAllSessions({
          status: "error",
          message: error instanceof Error ? error.message : "Failed to load sessions",
        });
      });
    return () => controller.abort();
  }, [target, query]);

  // Every open row without its sessions yet gets them — whether it was
  // clicked open or the preference opened it. Rows are fetched one user at
  // a time so each stays complete under its own cap; with the preference on
  // that is one request per user, which the browser queues, and is the
  // trade the user made in choosing it.
  // biome-ignore lint/correctness/useExhaustiveDependencies: userSessions and isOpen are read, not triggers — the loading marker this sets is what stops a refetch
  useEffect(() => {
    if (target === "avg-session") return;
    const pending = users.filter((user) => isOpen(user.key) && !userSessions[user.key]);
    if (pending.length === 0) return;

    setUserSessions((current) => {
      const next = { ...current };
      for (const user of pending) next[user.key] = { status: "loading" };
      return next;
    });
    const separator = query.startsWith("?") ? "&" : "?";
    for (const user of pending) {
      // `user_ids` wants the compound "instance_id:user_id" key; a bare id
      // is silently ignored by _user_instance_filter.
      clientFetch<SessionRow[]>(
        `/api/dashboard/sessions${query}${separator}` +
          `user_ids=${encodeURIComponent(user.key)}&limit=${SESSION_LIMIT}`,
      )
        .then((rows) => {
          setUserSessions((current) => ({
            ...current,
            [user.key]: { status: "ok", rows },
          }));
        })
        .catch((error: unknown) => {
          setUserSessions((current) => ({
            ...current,
            [user.key]: {
              status: "error",
              message: error instanceof Error ? error.message : "Failed to load sessions",
            },
          }));
        });
    }
  }, [target, query, users, flipped, listsExpanded]);

  /** One user's sessions, or where they are on the way in. */
  function detailOf(key: string) {
    const detail = userSessions[key];
    if (!detail || detail.status === "loading")
      return <Spinner label="Loading sessions…" />;
    if (detail.status === "error") {
      return (
        <p className="text-xs text-error" role="alert">
          {detail.message}
        </p>
      );
    }
    return <SessionBody rows={detail.rows} timeZone={timeZone} multiDay={multiDay} />;
  }

  if (target === "avg-session") {
    return (
      <Modal
        title="Sessions by day"
        subtitle={`${metrics.start_date} – ${metrics.end_date}`}
        onClose={onClose}
      >
        {allSessions.status === "loading" && <Spinner label="Loading sessions…" />}
        {allSessions.status === "error" && (
          <p className="text-sm text-error" role="alert">
            {allSessions.message}
          </p>
        )}
        {allSessions.status === "ok" && (
          <SessionsByDayTable
            rows={allSessions.rows}
            timeZone={timeZone}
            capped={isCapped(allSessions.rows, SESSION_LIMIT)}
            defaultExpanded={listsExpanded}
          />
        )}
      </Modal>
    );
  }

  return (
    <Modal
      title="Playback per user"
      subtitle={`${formatCount(users.length)} users · ${formatCount(metrics.total_plays)} plays · ${formatDuration(metrics.total_watch_time_seconds)}`}
      onClose={onClose}
    >
      {users.length === 0 ? (
        <p className="text-sm text-muted">No playback recorded in this range.</p>
      ) : compact ? (
        // Four columns on a phone pushed the numbers off the right edge. One
        // tappable row per user: name and server, plays and watch time.
        <ul className="divide-y divide-border text-sm">
          {users.map((user) => {
            const open = isOpen(user.key);
            return (
              <li key={user.key}>
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => toggle(user.key)}
                  className={cn(
                    "flex w-full items-center gap-1 py-2.5 text-left",
                    open && "bg-surface-2",
                  )}
                >
                  <Chevron open={open} />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate font-medium">{user.name}</span>
                    <span className="text-xs text-muted">{user.server || "—"}</span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-0.5 tabular-nums">
                    <span>{formatDuration(user.seconds)}</span>
                    <span className="text-xs text-muted">
                      {formatCount(user.plays)} {user.plays === 1 ? "play" : "plays"}
                    </span>
                  </span>
                </button>
                {open && <div className="bg-bg/60 px-2 pb-2">{detailOf(user.key)}</div>}
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="py-1 font-normal">User</th>
                <th className="w-40 py-1 font-normal">Server</th>
                <th className="w-20 py-1 text-right font-normal">Plays</th>
                <th className="w-28 py-1 text-right font-normal">Watch time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((user) => {
                const open = isOpen(user.key);
                return (
                  <Fragment key={user.key}>
                    <ExpandRow open={open} onToggle={() => toggle(user.key)}>
                      <td className="py-1">
                        <Chevron
                          open={open}
                          onToggle={() => toggle(user.key)}
                          label={`Sessions for ${user.name}`}
                        />
                        {user.name}
                      </td>
                      <td className="py-1 text-muted">{user.server || "—"}</td>
                      <td className="py-1 text-right tabular-nums">
                        {formatCount(user.plays)}
                      </td>
                      <td className="py-1 text-right tabular-nums">
                        {formatDuration(user.seconds)}
                      </td>
                    </ExpandRow>
                    {open && (
                      <tr>
                        <td colSpan={4} className="bg-bg/60 px-3 pb-3">
                          {detailOf(user.key)}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}
