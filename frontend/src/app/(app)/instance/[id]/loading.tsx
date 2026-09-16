/**
 * Shown under the instance tabs while a tab's server fetch is in flight —
 * a card the shape of the one that follows, so the page does not go blank
 * between one tab and the next.
 */
export default function InstanceLoading() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="animate-pulse rounded-lg bg-surface"
    >
      <div className="border-b border-border px-4 py-3">
        <div className="h-4 w-32 rounded-md bg-surface-2" />
      </div>
      <div className="flex flex-col gap-3 p-4">
        {[1, 2, 3, 4, 5].map((line) => (
          <div key={line} className="h-4 rounded-md bg-surface-2" />
        ))}
      </div>
    </div>
  );
}
