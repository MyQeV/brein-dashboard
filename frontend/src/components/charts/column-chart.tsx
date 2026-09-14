"use client";

import { useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { ChartTooltip } from "./chart-tooltip";

export type ColumnDatum = {
  id: string;
  /** Names the column in the tooltip and aria text. */
  label: string;
  /** Printed under the column; "" prints nothing (thin out a 24-hour axis). */
  axisLabel?: string;
  value: number;
};

/**
 * Single-series magnitude over an ordered axis: hours, weekdays, days.
 *
 * One hue (the accent), columns capped at 24px inside slots that share the
 * width, a hairline baseline, one value label on the tallest column. The
 * slot, not the column, is the hit target — a 4px column at 03:00 is not
 * something a pointer can find.
 */
export function ColumnChart({
  data,
  format,
  emptyLabel = "No data for this range.",
  height = 120,
  ariaLabel,
  onColumnClick,
}: {
  data: ColumnDatum[];
  format: (value: number) => string;
  emptyLabel?: string;
  height?: number;
  ariaLabel: string;
  onColumnClick?: (datum: ColumnDatum) => void;
}) {
  const plotRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<{ index: number; x: number; y: number } | null>(
    null,
  );

  if (data.length === 0 || data.every((datum) => datum.value === 0)) {
    return <p className="py-6 text-sm text-muted">{emptyLabel}</p>;
  }

  const max = Math.max(...data.map((datum) => datum.value));
  const maxIndex = data.findIndex((datum) => datum.value === max);

  function place(index: number, target: HTMLElement) {
    const box = plotRef.current?.getBoundingClientRect();
    const spot = target.getBoundingClientRect();
    if (!box) return;
    setHover({
      index,
      x: spot.left - box.left + spot.width / 2,
      y: spot.top - box.top + (spot.height - columnHeight(data[index].value)),
    });
  }

  function columnHeight(value: number): number {
    return Math.round(Math.max(max > 0 ? (value / max) * height : 0, value > 0 ? 2 : 0));
  }

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: onMouseLeave only clears hover state; the operable elements are the buttons inside
    <div className="flex flex-col gap-2 pt-5" onMouseLeave={() => setHover(null)}>
      {/* biome-ignore lint/a11y/useAriaPropsSupportedByRole: both group and img roles support aria-label */}
      <div
        ref={plotRef}
        className="relative flex items-end gap-1 border-b border-border"
        style={{ height }}
        role={onColumnClick ? "group" : "img"}
        aria-label={`${ariaLabel}. ${data
          .map((datum) => `${datum.label}: ${format(datum.value)}`)
          .join(", ")}`}
      >
        {/* One recessive midline: a bare column reads as no scale at all. */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-border/60"
        />

        {hover && (
          <ChartTooltip
            x={hover.x}
            y={hover.y}
            value={format(data[hover.index].value)}
            label={
              onColumnClick
                ? `${data[hover.index].label} · click for sessions`
                : data[hover.index].label
            }
          />
        )}

        {data.map((datum, index) => {
          const slotClass = cn(
            "relative flex h-full min-w-0 flex-1 items-end justify-center rounded-sm",
            hover?.index === index && "bg-surface-2",
          );

          return onColumnClick ? (
            <button
              key={datum.id}
              type="button"
              aria-label={`${datum.label}: ${format(datum.value)}`}
              onClick={() => onColumnClick(datum)}
              onMouseEnter={(event) => place(index, event.currentTarget)}
              onFocus={(event) => place(index, event.currentTarget)}
              onBlur={() => setHover(null)}
              className={cn(slotClass, "cursor-pointer")}
            >
              {index === maxIndex ? (
                <span
                  aria-hidden="true"
                  className="absolute -top-5 text-[11px] tabular-nums whitespace-nowrap text-text"
                >
                  {format(datum.value)}
                </span>
              ) : null}
              <span
                className={cn(
                  "block w-full max-w-6 rounded-t-[4px] bg-accent",
                  hover?.index === index && "brightness-110",
                )}
                style={{ height: columnHeight(datum.value) }}
              />
            </button>
          ) : (
            // biome-ignore lint/a11y/noStaticElementInteractions: hover only positions the tooltip; the plot carries the accessible summary
            <div
              key={datum.id}
              onMouseEnter={(event) => place(index, event.currentTarget)}
              className={slotClass}
            >
              {index === maxIndex ? (
                <span
                  aria-hidden="true"
                  className="absolute -top-5 text-[11px] tabular-nums whitespace-nowrap text-text"
                >
                  {format(datum.value)}
                </span>
              ) : null}
              <span
                className={cn(
                  "block w-full max-w-6 rounded-t-[4px] bg-accent",
                  hover?.index === index && "brightness-110",
                )}
                style={{ height: columnHeight(datum.value) }}
              />
            </div>
          );
        })}
      </div>

      <div
        className="grid gap-1 text-[11px] text-muted"
        style={{ gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))` }}
      >
        {data.map((datum) => (
          <span key={datum.id} className="truncate text-center tabular-nums">
            {datum.axisLabel ?? datum.label}
          </span>
        ))}
      </div>
    </div>
  );
}
