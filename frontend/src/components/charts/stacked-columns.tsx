"use client";

import type { RefObject } from "react";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";

export type StackSegment = { key: string; name: string; seconds: number; color: string };
export type Stack = { date: string; total: number; segments: StackSegment[] };

/** Columns get a fixed width once there are too many to share the width. */
const DENSE_COLUMN_PX = 6;

/**
 * One stacked column per day, a segment per user.
 *
 * Columns fill their slot (an 8px gap between them), segments are separated
 * by a 2px gap in the surface colour, the top segment is rounded. Segment
 * heights are pixels against the visible maximum, so hiding a user regrows
 * the rest. The selected segment carries a ring in text ink so it still reads
 * on its own colour.
 */
export function StackedColumns({
  stacks,
  maxTotal,
  plotHeight,
  dense,
  labelStride,
  plotRef,
  selected,
  dayLabel,
  onSegmentClick,
  onHover,
}: {
  stacks: Stack[];
  maxTotal: number;
  plotHeight: number;
  dense: boolean;
  labelStride: number;
  /** The measured box the caller's ResizeObserver watches and the tooltip is placed in. */
  plotRef: RefObject<HTMLDivElement | null>;
  selected: { key: string; date: string } | null;
  dayLabel: (date: string) => string;
  onSegmentClick: (date: string, segment: StackSegment) => void;
  onHover: (hover: { text: string; sub: string; x: number; y: number } | null) => void;
}) {
  const tallest = stacks.reduce(
    (best, stack) => (stack.total > best.total ? stack : best),
    stacks[0] ?? { date: "", total: 0, segments: [] },
  );

  function hoverAt(
    stack: Stack,
    segment: StackSegment,
    clientX: number,
    clientY: number,
  ) {
    const box = plotRef.current?.getBoundingClientRect();
    if (!box) return;
    onHover({
      text: formatDuration(segment.seconds),
      sub: `${segment.name} · ${dayLabel(stack.date)}`,
      x: clientX - box.left,
      y: clientY - box.top,
    });
  }

  return (
    <div ref={plotRef} className={cn("flex flex-col", dense && "overflow-x-auto")}>
      <div
        className={cn("relative flex items-end", dense ? "w-max gap-px" : "gap-2")}
        style={{ height: plotHeight }}
      >
        {/* One recessive midline with its value: a bare column reads as no scale. */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-border/60"
        />
        {maxTotal > 0 && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute right-0 top-1/2 -translate-y-full pb-0.5 text-[10px] tabular-nums text-muted"
          >
            {formatDuration(Math.round(maxTotal / 2))}
          </span>
        )}

        {stacks.map((stack) => (
          <div
            key={stack.date}
            className={cn(
              "relative flex flex-col-reverse justify-start overflow-visible",
              dense ? "shrink-0" : "min-w-0 flex-1",
            )}
            style={dense ? { width: DENSE_COLUMN_PX } : undefined}
          >
            {/* Only the tallest day carries a value; the rest is the tooltip's job. */}
            {!dense && stack.date === tallest.date && stack.total > 0 && (
              <span
                aria-hidden="true"
                className="absolute -top-5 left-1/2 -translate-x-1/2 text-[11px] tabular-nums whitespace-nowrap text-text"
              >
                {formatDuration(stack.total)}
              </span>
            )}
            {stack.segments.map((segment, index) => {
              const isSelected =
                selected?.key === segment.key && selected.date === stack.date;
              const isTop = index === stack.segments.length - 1;
              return (
                <button
                  key={segment.key}
                  type="button"
                  aria-label={`${segment.name} on ${stack.date}: ${formatDuration(segment.seconds)}`}
                  onClick={() => onSegmentClick(stack.date, segment)}
                  // Not a tab stop: a year of days times fifty users is
                  // thousands of 2px buttons sitting between the chart and
                  // everything after it. The per-user-per-day list below is
                  // the keyboard path to the same detail.
                  tabIndex={-1}
                  onMouseMove={(event) =>
                    hoverAt(stack, segment, event.clientX, event.clientY)
                  }
                  onMouseLeave={() => onHover(null)}
                  className={cn(
                    "w-full cursor-pointer transition-[filter] hover:brightness-110",
                    index > 0 && "border-b-2 border-surface",
                    isTop && "rounded-t-[4px]",
                    isSelected && "outline-2 outline-offset-1 outline-text",
                  )}
                  style={{
                    height: Math.max(
                      4,
                      Math.round(
                        maxTotal > 0 ? (segment.seconds / maxTotal) * plotHeight : 0,
                      ),
                    ),
                    background: segment.color,
                  }}
                />
              );
            })}
          </div>
        ))}
      </div>

      <div
        className={cn(
          "flex border-t border-border pt-1",
          dense ? "w-max gap-px" : "gap-2",
        )}
      >
        {stacks.map((stack, index) => (
          <span
            key={stack.date}
            className={cn(
              "text-[11px] tabular-nums text-muted",
              dense
                ? "shrink-0 overflow-visible whitespace-nowrap text-left"
                : "min-w-0 flex-1 truncate text-center",
              selected?.date === stack.date && "text-text",
            )}
            style={dense ? { width: DENSE_COLUMN_PX } : undefined}
          >
            {index % labelStride === 0 ? dayLabel(stack.date) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
