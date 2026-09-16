"use client";

import {
  isCapped,
  type SessionRow,
  SessionsByDayTable,
} from "@/components/sessions-by-day";
import { Modal } from "@/components/ui/modal";
import { Spinner } from "@/components/ui/spinner";
import { formatDuration } from "@/lib/format";
import { MODAL_LISTS_EXPANDED, useBooleanPreference } from "@/lib/preferences";
import { rowNumber } from "@/lib/rows";
import type { MediaDrillRow } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export type DrillTarget = { drillType: string; id: string; title: string };

/**
 * Per backend, newest first. The store's own default was 50 for an item drill,
 * which quietly turned a year of plays into the last fifty — and the modal
 * totals what it is given.
 */
const DRILL_LIMIT = 500;

export function DrillModal({
  target,
  query,
  timeZone,
  onClose,
}: {
  target: DrillTarget;
  query: string;
  /** The API buckets by the app's zone, so the rows must be read in it too. */
  timeZone?: string;
  onClose: () => void;
}) {
  // A user drill is one user's sessions, so the column would repeat the
  // dialog's own title on every row.
  const showUser = target.drillType !== "user";
  const listsExpanded = useBooleanPreference(MODAL_LISTS_EXPANDED);

  const separator = query.startsWith("?") ? "&" : "?";
  const state = useApi<MediaDrillRow[]>(
    `/api/dashboard/media-drill${query}${separator}` +
      `drill_type=${encodeURIComponent(target.drillType)}` +
      `&id=${encodeURIComponent(target.id)}&limit=${DRILL_LIMIT}`,
  );
  const rows = state.status === "ok" ? state.data : [];
  const total = rows.reduce((sum, row) => sum + rowNumber(row, ["duration_seconds"]), 0);
  const subtitle =
    state.status === "ok" && rows.length > 0
      ? `${rows.length} ${rows.length === 1 ? "session" : "sessions"} · ${formatDuration(total)}`
      : undefined;

  return (
    <Modal title={target.title} subtitle={subtitle} onClose={onClose}>
      {state.status === "loading" && <Spinner label="Loading details…" />}

      {state.status === "error" && (
        <p className="text-sm text-error" role="alert">
          {state.message}
        </p>
      )}

      {state.status === "ok" && rows.length === 0 && (
        <p className="text-sm text-muted">No sessions for this selection.</p>
      )}

      {/* Grouped by day with a subtotal each, like the average-session
          breakdown: a drill spans the whole range, so a flat list mixed dates
          together and never said how much belonged to any of them. */}
      {state.status === "ok" && rows.length > 0 && (
        <SessionsByDayTable
          rows={rows as SessionRow[]}
          timeZone={timeZone || "UTC"}
          showUser={showUser}
          capped={isCapped(rows as SessionRow[], DRILL_LIMIT)}
          defaultExpanded={listsExpanded}
        />
      )}
    </Modal>
  );
}
