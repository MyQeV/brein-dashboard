"use client";

import { CHART_SLOTS, OTHER_COLOR, seriesColor } from "./chart-theme";

export type StackedDatum = { id: string; label: string; value: number };

type Segment = StackedDatum & { color: string; share: number };

/**
 * Part-to-whole as one 100% bar with a legend — the one place the dashboard
 * uses categorical colour. Zero-value classes are named below the legend
 * rather than drawn as 0% slivers, and anything past the eighth class folds
 * into "Other" so the palette is never cycled.
 */
export function StackedBar({
  data,
  format,
  emptyLabel = "No data for this range.",
  onSegmentClick,
}: {
  data: StackedDatum[];
  format: (value: number) => string;
  emptyLabel?: string;
  onSegmentClick?: (datum: StackedDatum) => void;
}) {
  const total = data.reduce((sum, datum) => sum + Math.max(0, datum.value), 0);
  if (total <= 0) return <p className="py-6 text-sm text-muted">{emptyLabel}</p>;

  const sorted = [...data].sort((a, b) => b.value - a.value);
  const drawn = sorted.filter((datum) => datum.value > 0);
  const empty = sorted.filter((datum) => datum.value <= 0);

  const head = drawn.slice(0, CHART_SLOTS);
  const tail = drawn.slice(CHART_SLOTS);
  const segments: Segment[] = head.map((datum, index) => ({
    ...datum,
    color: seriesColor(index),
    share: datum.value / total,
  }));
  if (tail.length > 0) {
    const value = tail.reduce((sum, datum) => sum + datum.value, 0);
    segments.push({
      id: "__other__",
      label: "Other",
      value,
      color: OTHER_COLOR,
      share: value / total,
    });
  }

  const percent = (share: number) => `${Math.round(share * 100)}%`;

  return (
    <div className="flex flex-col gap-3">
      {/* biome-ignore lint/a11y/useAriaPropsSupportedByRole: both group and img support aria-label */}
      <div
        className="flex h-2.5 gap-0.5 overflow-hidden rounded-[5px]"
        role={onSegmentClick ? "group" : "img"}
        aria-label={segments
          .map((segment) => `${segment.label} ${percent(segment.share)}`)
          .join(", ")}
      >
        {segments.map((segment) =>
          onSegmentClick && segment.id !== "__other__" ? (
            <button
              key={segment.id}
              type="button"
              aria-label={`${segment.label}: ${format(segment.value)}`}
              onClick={() => onSegmentClick(segment)}
              className="block h-full cursor-pointer hover:brightness-110"
              style={{ width: `${segment.share * 100}%`, background: segment.color }}
            />
          ) : (
            <span
              key={segment.id}
              className="block h-full"
              style={{ width: `${segment.share * 100}%`, background: segment.color }}
            />
          ),
        )}
      </div>

      <ul className="flex flex-col gap-2 text-sm">
        {segments.map((segment) => {
          const row = (
            <>
              <span
                aria-hidden="true"
                className="size-2 shrink-0 rounded-full"
                style={{ background: segment.color }}
              />
              <span className="min-w-0 flex-1 truncate">{segment.label}</span>
              <span className="tabular-nums text-muted">
                {percent(segment.share)} · {format(segment.value)}
              </span>
            </>
          );
          return (
            <li key={segment.id}>
              {onSegmentClick && segment.id !== "__other__" ? (
                <button
                  type="button"
                  onClick={() => onSegmentClick(segment)}
                  className="-mx-2 flex w-[calc(100%+1rem)] cursor-pointer items-center gap-2 rounded-sm px-2 py-0.5 text-left hover:bg-surface-2"
                >
                  {row}
                </button>
              ) : (
                <div className="flex items-center gap-2 py-0.5">{row}</div>
              )}
            </li>
          );
        })}
      </ul>

      {empty.length > 0 && (
        <p className="text-xs text-muted">
          No time: {empty.map((datum) => datum.label).join(", ")}
        </p>
      )}
    </div>
  );
}
