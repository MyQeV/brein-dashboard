"use client";

import { type ReactNode, useState } from "react";
import { cn } from "@/lib/cn";

export type RankedDatum = {
  id: string;
  label: string;
  value: number;
  /** An avatar or poster; every row in a list has one or none has one. */
  leading?: ReactNode;
};

/** The initial in a circle — the identity slot until posters arrive. */
export function RankAvatar({
  name,
  highlight = false,
}: {
  name: string;
  highlight?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-7 items-center justify-center rounded-full text-xs font-semibold",
        highlight ? "bg-accent text-accent-ink" : "bg-surface-2 text-text",
      )}
    >
      {(name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}

/**
 * Ranked magnitude: one hue, the longest bar is the largest value, identity
 * from the label. Replaces the doughnuts — 78 / 21 / 0 % is a list, not a
 * part-to-whole.
 */
export function RankedBars({
  data,
  format,
  limit = 5,
  emptyLabel = "No data for this range.",
  onRowClick,
  footer,
}: {
  data: RankedDatum[];
  format: (value: number) => string;
  /** Rows shown before "show all". */
  limit?: number;
  emptyLabel?: string;
  onRowClick?: (datum: RankedDatum) => void;
  /** Replaces the "+N more" line when there is nothing to expand. */
  footer?: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const sorted = [...data].sort((a, b) => b.value - a.value);
  const rows = showAll ? sorted : sorted.slice(0, limit);
  const max = sorted[0]?.value ?? 0;
  const hasLeading = sorted.some((datum) => datum.leading !== undefined);
  const hidden = sorted.length - rows.length;

  if (sorted.length === 0 || max <= 0) {
    return <p className="py-6 text-sm text-muted">{emptyLabel}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-1.5">
        {rows.map((datum) => {
          const body = (
            <>
              {hasLeading && (
                <span className="flex size-7 shrink-0 items-center justify-center">
                  {datum.leading}
                </span>
              )}
              <span className="flex min-w-0 flex-col gap-1.5">
                <span className="truncate text-sm" title={datum.label}>
                  {datum.label}
                </span>
                <span className="block h-2 rounded-r-[4px] bg-surface-2">
                  <span
                    className="block h-full rounded-r-[4px] bg-accent"
                    style={{ width: `${(datum.value / max) * 100}%` }}
                  />
                </span>
              </span>
              <span className="text-xs tabular-nums text-muted">
                {format(datum.value)}
              </span>
              {onRowClick && (
                <span
                  aria-hidden="true"
                  className="text-muted opacity-0 transition-opacity group-hover:opacity-100"
                >
                  ›
                </span>
              )}
            </>
          );
          const rowClass = cn(
            "grid w-full items-center gap-2.5 text-left",
            hasLeading
              ? "grid-cols-[1.75rem_minmax(0,1fr)_auto_0.75rem]"
              : "grid-cols-[minmax(0,1fr)_auto_0.75rem]",
          );
          return (
            <li key={datum.id}>
              {onRowClick ? (
                <button
                  type="button"
                  onClick={() => onRowClick(datum)}
                  className={cn(
                    rowClass,
                    "group -mx-2 cursor-pointer rounded-sm px-2 py-1 hover:bg-surface-2",
                  )}
                  style={{ width: "calc(100% + 1rem)" }}
                >
                  {body}
                </button>
              ) : (
                <div className={rowClass}>{body}</div>
              )}
            </li>
          );
        })}
      </ul>

      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="self-start text-xs text-muted hover:text-text"
        >
          +{hidden} more · <span className="text-accent">show all</span>
        </button>
      ) : showAll && sorted.length > limit ? (
        <button
          type="button"
          onClick={() => setShowAll(false)}
          className="self-start text-xs text-accent hover:text-text"
        >
          show fewer
        </button>
      ) : footer ? (
        <span className="text-xs text-muted">{footer}</span>
      ) : null}
    </div>
  );
}
