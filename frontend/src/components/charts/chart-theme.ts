/**
 * Chart colours.
 *
 * Series colours are the theme's CSS variables (`--chart-1` … `--chart-8`,
 * `--chart-other`, `--ramp-1` … `--ramp-5` in globals.css), validated per
 * theme with the dataviz palette validator. Every chart is DOM or SVG, so a
 * `var()` string is all a caller needs.
 *
 * Assign in fixed order, never cycled. Beyond the eighth series the answer is
 * the "Other" grey, not a ninth hue — except where every entity keeps its own
 * segment (see `rankColor`).
 */
export const CHART_SLOTS = 8;

export function seriesColor(index: number): string {
  return index >= 0 && index < CHART_SLOTS
    ? `var(--chart-${index + 1})`
    : "var(--chart-other)";
}

/** The aggregated "Other" slice — never one of the categorical hues. */
export const OTHER_COLOR = "var(--chart-other)";

/**
 * A colour for every rank, for a chart that draws one segment per entity and
 * never aggregates — the Daily stack, where thirty users each keep their own
 * band. The eight validated slots come first; past them the hue steps round
 * the wheel by the golden angle, so neighbours in rank sit far apart, with
 * lightness and chroma from the theme so a light theme stays readable. These
 * are not colour-vision validated: the alternative was one grey for everyone
 * past eighth, which nobody can tell apart.
 */
export function rankColor(index: number): string {
  if (index < CHART_SLOTS) return seriesColor(index);
  const hue = Math.round(((index - CHART_SLOTS) * 137.508 + 20) % 360);
  return `oklch(var(--chart-gen-l) var(--chart-gen-c) ${hue})`;
}
