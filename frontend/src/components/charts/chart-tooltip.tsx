/**
 * The hover readout, positioned by the caller inside a `relative` box.
 * Value first and strong, label second and muted: the reader already knows
 * what they are pointing at and wants the number.
 */
export function ChartTooltip({
  x,
  y,
  value,
  label,
}: {
  x: number;
  y: number;
  value: string;
  label: string;
}) {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute z-10 flex -translate-x-1/2 -translate-y-full flex-col gap-0.5 rounded-sm border border-border bg-surface-2 px-2.5 py-1.5 whitespace-nowrap shadow-(--shadow-elevated)"
      style={{ left: x, top: Math.max(y - 8, 0) }}
    >
      <span className="text-sm font-semibold tabular-nums">{value}</span>
      <span className="text-[11px] text-muted">{label}</span>
    </div>
  );
}
