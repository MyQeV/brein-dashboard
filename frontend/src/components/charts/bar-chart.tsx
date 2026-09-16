import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";

/**
 * `id` is the React key when set; labels can repeat ("Unknown series" for
 * every series whose parent has not synced), and a repeated key drops bars.
 */
export type BarDatum = { label: string; value: number; sublabel?: string; id?: string };

/**
 * The plot area, in pixels rather than a percentage of the container.
 * A percentage height only resolves against a definite parent height, and the
 * column that holds each bar is a flex item whose height is not definite —
 * which silently collapsed every bar to zero.
 */
const PLOT_HEIGHT_PX = 168;

/** Room for the value printed above each bar, when there is room to print it. */
const VALUE_ROW_PX = 16;

/** Past this many bars the values collide, so only the axis labels remain. */
const MAX_BARS_WITH_VALUES = 8;

/**
 * Single-series magnitude chart.
 *
 * One hue (the theme accent) rather than a categorical palette: every series
 * here is magnitude, and identity comes from the axis labels. That also means
 * no legend — with one colour, the title already says what is plotted.
 * Values render in text ink, never the series colour.
 */
export function BarChart({
  data,
  orientation = "vertical",
  format = formatCount,
  emptyLabel = "No data for this range.",
  maxBarThickness = 24,
  onBarClick,
}: {
  data: BarDatum[];
  orientation?: "vertical" | "horizontal";
  format?: (value: number) => string;
  emptyLabel?: string;
  maxBarThickness?: number;
  onBarClick?: (datum: BarDatum) => void;
}) {
  if (data.length === 0 || data.every((datum) => datum.value === 0)) {
    return <p className="py-6 text-sm text-muted">{emptyLabel}</p>;
  }

  const max = Math.max(...data.map((datum) => datum.value));

  if (orientation === "horizontal") {
    return (
      <ul className="flex flex-col gap-2">
        {data.map((datum) => (
          <li
            key={datum.id ?? datum.label}
            className="grid grid-cols-[10rem_1fr_auto] items-center gap-3"
          >
            <span className="truncate text-sm" title={datum.label}>
              {datum.label}
            </span>
            <span className="block h-2 rounded-r-[4px] bg-surface-2">
              <span
                className="block h-full rounded-r-[4px] bg-accent"
                style={{ width: `${max > 0 ? (datum.value / max) * 100 : 0}%` }}
              />
            </span>
            <span className="text-sm tabular-nums text-muted">{format(datum.value)}</span>
          </li>
        ))}
      </ul>
    );
  }

  const showValues = data.length <= MAX_BARS_WITH_VALUES;
  const barArea = PLOT_HEIGHT_PX - (showValues ? VALUE_ROW_PX : 0);
  // At most five labels below `sm`; thirty labels do not fit a phone.
  const phoneStride = Math.max(1, Math.ceil(data.length / 5));

  return (
    <div className="flex flex-col">
      {/* biome-ignore lint/a11y/useAriaPropsSupportedByRole: both group and img support aria-label */}
      <div
        className="relative flex items-end gap-1"
        style={{ height: PLOT_HEIGHT_PX }}
        // An img has presentational children: with clickable bars the buttons
        // are focusable but hidden from assistive tech, so a screen-reader
        // user lands on something that is not announced. A group keeps them.
        role={onBarClick ? "group" : "img"}
        aria-label={`Bar chart. ${data
          .map((datum) => `${datum.label}: ${format(datum.value)}`)
          .join(", ")}`}
      >
        {/* One recessive midline: a bare bar reads as no scale at all. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-border/60"
        />

        {data.map((datum) => {
          const height = Math.round(
            Math.max(
              max > 0 ? (datum.value / max) * barArea : 0,
              datum.value > 0 ? 2 : 0,
            ),
          );
          const bar = (
            <span
              key={datum.id ?? datum.label}
              className={cn(
                "block w-full rounded-t-[4px] bg-accent",
                onBarClick && "transition-opacity group-hover:opacity-75",
              )}
              style={{ height, maxWidth: maxBarThickness }}
            />
          );
          const column = (
            <>
              {showValues && (
                <span
                  className="text-[10px] leading-4 tabular-nums text-muted"
                  style={{ height: VALUE_ROW_PX }}
                >
                  {format(datum.value)}
                </span>
              )}
              {bar}
            </>
          );

          return onBarClick ? (
            <button
              key={datum.id ?? datum.label}
              type="button"
              title={`${datum.label}: ${format(datum.value)}`}
              aria-label={`${datum.label}: ${format(datum.value)}`}
              onClick={() => onBarClick(datum)}
              className="group relative flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-end"
            >
              {column}
            </button>
          ) : (
            <div
              key={datum.id ?? datum.label}
              title={`${datum.label}: ${format(datum.value)}`}
              className="relative flex min-w-0 flex-1 flex-col items-center justify-end"
            >
              {column}
            </div>
          );
        })}
      </div>

      {/* The baseline sits under the bars, not behind them. */}
      <div className="flex gap-1 border-t border-border pt-1">
        {data.map((datum, index) => (
          <span
            key={datum.id ?? datum.label}
            className="min-w-0 flex-1 text-center text-[11px] text-muted max-sm:overflow-visible max-sm:whitespace-nowrap sm:truncate"
          >
            <span className="sm:hidden">
              {index % phoneStride === 0 ? datum.sublabel || datum.label : ""}
            </span>
            <span className="hidden sm:inline">{datum.sublabel ?? datum.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
