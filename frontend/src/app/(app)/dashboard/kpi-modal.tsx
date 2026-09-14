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
import { clientFetch } from "@/lib/client-fetch";
import { formatCount, formatDuration } from "@/lib/format";
import { rowNumber, rowText } from "@/lib/rows";
import type { MediaMetrics } from "@/lib/types";

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
  const multiDay = metrics.start_date !== metrics.end_date;

  // A set, not one key: opening a row must not close the ones already open.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  function toggle(key: string) {
    setExpanded((current) => {
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

  function toggleUser(user: UserRow) {
    const wasOpen = expanded.has(user.key);
    toggle(user.key);
    if (wasOpen) return;
    if (userSessions[user.key]) return;

    setUserSessions((current) => ({ ...current, [user.key]: { status: "loading" } }));
    const separator = query.startsWith("?") ? "&" : "?";
    // `user_ids` wants the compound "instance_id:user_id" key; a bare id is
    // silently ignored by _user_instance_filter.
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
                const open = expanded.has(user.key);
                const detail = userSessions[user.key];
                return (
                  <Fragment key={user.key}>
                    <ExpandRow open={open} onToggle={() => toggleUser(user)}>
                      <td className="py-1">
                        <Chevron
                          open={open}
                          onToggle={() => toggleUser(user)}
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
                          {(!detail || detail.status === "loading") && (
                            <Spinner label="Loading sessions…" />
                          )}
                          {detail?.status === "error" && (
                            <p className="text-xs text-error" role="alert">
                              {detail.message}
                            </p>
                          )}
                          {detail?.status === "ok" && (
                            <SessionBody
                              rows={detail.rows}
                              timeZone={timeZone}
                              multiDay={multiDay}
                            />
                          )}
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
