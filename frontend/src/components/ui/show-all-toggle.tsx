/**
 * The line under a list cut at `limit`: "+N more · show all" while it is
 * cut, "show fewer" once it has been opened, nothing when it was never cut.
 */
export function ShowAllToggle({
  total,
  limit,
  expanded,
  onToggle,
}: {
  total: number;
  limit: number;
  expanded: boolean;
  onToggle: (expanded: boolean) => void;
}) {
  if (total <= limit) return null;
  return expanded ? (
    <button
      type="button"
      onClick={() => onToggle(false)}
      className="self-start text-xs text-accent hover:text-text"
    >
      show fewer
    </button>
  ) : (
    <button
      type="button"
      onClick={() => onToggle(true)}
      className="self-start text-xs text-muted hover:text-text"
    >
      +{total - limit} more · <span className="text-accent">show all</span>
    </button>
  );
}
