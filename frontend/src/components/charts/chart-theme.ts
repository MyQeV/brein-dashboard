/**
 * Chart colours.
 *
 * Series colours are the theme's CSS variables (`--chart-1` … `--chart-8`,
 * `--chart-other`, `--ramp-1` … `--ramp-5` in globals.css), validated per
 * theme with the dataviz palette validator. Every chart is DOM or SVG, so a
 * `var()` string is all a caller needs.
 *
 * Assign in fixed order, never cycled. Beyond the eighth series the answer is
 * the "Other" grey, not a ninth hue.
 */
export const CHART_SLOTS = 8;

export function seriesColor(index: number): string {
  return index >= 0 && index < CHART_SLOTS
    ? `var(--chart-${index + 1})`
    : "var(--chart-other)";
}

/** The aggregated "Other" slice — never one of the categorical hues. */
export const OTHER_COLOR = "var(--chart-other)";
