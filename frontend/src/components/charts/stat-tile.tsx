import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { formatCount, formatDuration } from "@/lib/format";
import { Sparkline } from "./sparkline";

/** How a headline number compares with the previous window. */
export type Delta = {
  current: number;
  previous: number;
  /** percent: "+38%"; duration: "−4m"; count: "+6". */
  mode: "percent" | "duration" | "count";
};

function describeDelta(
  delta: Delta,
): { text: string; tone: "up" | "down" | "flat" } | null {
  const diff = delta.current - delta.previous;
  const tone = diff > 0 ? "up" : diff < 0 ? "down" : "flat";
  const sign = diff > 0 ? "+" : diff < 0 ? "−" : "±";
  if (delta.mode === "percent") {
    // No previous value means no ratio; showing "+∞%" helps nobody.
    if (delta.previous <= 0) return null;
    return {
      text: `${sign}${Math.abs(Math.round((diff / delta.previous) * 100))}%`,
      tone,
    };
  }
  const magnitude =
    delta.mode === "duration"
      ? formatDuration(Math.abs(diff))
      : formatCount(Math.abs(diff));
  return { text: `${sign}${magnitude}`, tone };
}

const TONE: Record<"up" | "down" | "flat", string> = {
  up: "text-success",
  down: "text-error",
  flat: "text-muted",
};

/** A headline number is a stat tile, not a one-bar bar chart. */
export function StatTile({
  label,
  value,
  hint,
  delta,
  deltaLabel,
  sparkline,
  wideSparkline = false,
  hero = false,
  onClick,
}: {
  label: string;
  value: string;
  hint?: string;
  delta?: Delta;
  /** Follows the delta in muted ink: "vs previous 7 days". */
  deltaLabel?: string;
  /** Per-period values, oldest first. */
  sparkline?: number[];
  /**
   * Draw the line under the number at the tile's full width, as the hero
   * does, instead of the small trace beside it. For a series with hundreds
   * of points — a year of daily peaks — 88px is a smudge.
   */
  wideSparkline?: boolean;
  /** The one number the page leads with: bigger, with a full-width area line. */
  hero?: boolean;
  /** Given, the tile becomes the button that opens its breakdown. */
  onClick?: () => void;
}) {
  const described = delta ? describeDelta(delta) : null;

  const body = (
    <div className={cn("flex w-full flex-col text-left", hero ? "gap-4" : "gap-2")}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs uppercase tracking-wide text-muted">{label}</span>
        {onClick && (
          <span aria-hidden="true" className="text-muted">
            ›
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-32 flex-col gap-1">
          <span
            className={cn(
              "font-semibold leading-none tabular-nums",
              hero ? "text-6xl tracking-tight" : "text-3xl",
            )}
          >
            {value}
          </span>
          {described && (
            <span className={cn("text-xs tabular-nums", TONE[described.tone])}>
              {described.text}
              {deltaLabel && <span className="text-muted"> {deltaLabel}</span>}
            </span>
          )}
          {hint && (
            <span className="truncate text-xs text-muted" title={hint}>
              {hint}
            </span>
          )}
        </div>
        {sparkline && !hero && !wideSparkline && (
          <Sparkline values={sparkline} className="ml-auto shrink-0" />
        )}
      </div>
      {sparkline && (hero || wideSparkline) && (
        <Sparkline
          values={sparkline}
          width={316}
          height={hero ? 44 : 36}
          area
          stretch
          className={cn("w-full", hero ? "h-11" : "h-9")}
        />
      )}
    </div>
  );

  if (!onClick) return <Card>{body}</Card>;

  return (
    <Card className="transition-colors hover:bg-surface-2">
      <button type="button" onClick={onClick} className="w-full cursor-pointer">
        {body}
      </button>
    </Card>
  );
}
