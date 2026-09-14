/**
 * A 2px line with an end dot, sized by its props — the trend beside a stat.
 * Fewer than two points draws nothing: one point is not a trend.
 */
export function Sparkline({
  values,
  width = 88,
  height = 28,
  area = false,
  stretch = false,
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  /** Fill under the line at 10% — the hero tile's treatment. */
  area?: boolean;
  /** Fill the box the className sizes; the stroke and dot stay 2px/4px. */
  stretch?: boolean;
  className?: string;
}) {
  if (values.length < 2) return null;

  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  // Room for the 4px end dot at the top and bottom edges.
  const pad = 4;
  const stepX = width / (values.length - 1);
  const points = values.map((value, index) => ({
    x: index * stepX,
    y: pad + (1 - (value - min) / span) * (height - pad * 2),
  }));
  const line = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const path = points.map((p) => `L${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const last = points[points.length - 1];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio={stretch ? "none" : undefined}
      fill="none"
      aria-hidden="true"
      className={className}
      // The end dot sits on the right edge; without this its right half is cut.
      style={{ overflow: "visible" }}
    >
      {area && (
        <path
          d={`M0 ${height} ${path} L${width} ${height} Z`}
          fill="var(--accent)"
          fillOpacity="0.1"
          vectorEffect={stretch ? "non-scaling-stroke" : undefined}
        />
      )}
      <polyline
        points={line}
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect={stretch ? "non-scaling-stroke" : undefined}
      />
      <path
        d={`M${last.x.toFixed(1)} ${last.y.toFixed(1)}h0.01`}
        stroke="var(--surface)"
        strokeWidth="10"
        strokeLinecap="round"
        vectorEffect={stretch ? "non-scaling-stroke" : undefined}
      />
      <path
        d={`M${last.x.toFixed(1)} ${last.y.toFixed(1)}h0.01`}
        stroke="var(--accent)"
        strokeWidth="6"
        strokeLinecap="round"
        vectorEffect={stretch ? "non-scaling-stroke" : undefined}
      />
    </svg>
  );
}
