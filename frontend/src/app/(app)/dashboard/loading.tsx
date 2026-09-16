/**
 * Shown under the tab strip while a dashboard tab's server fetch is in
 * flight. Without it a navigation painted nothing until the whole RSC
 * payload had landed, so switching tabs looked like a dead click.
 */
export default function DashboardLoading() {
  return (
    <div role="status" aria-label="Loading" className="flex animate-pulse flex-col gap-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-col gap-2">
          <div className="h-5 w-32 rounded-md bg-surface-2" />
          <div className="h-4 w-56 rounded-md bg-surface-2" />
        </div>
        <div className="h-8 w-full rounded-md bg-surface-2 lg:w-96" />
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
        {[1, 2, 3, 4].map((tile) => (
          <div key={tile} className="h-20 rounded-lg bg-surface" />
        ))}
      </div>
      <div className="h-64 rounded-lg bg-surface" />
    </div>
  );
}
