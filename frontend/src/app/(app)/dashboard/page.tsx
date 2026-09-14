import type { Metadata } from "next";
import { loadMetricsPage, MetricsPageHeader } from "./metrics-page";
import { WatchtimeView } from "./watchtime-view";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage(props: PageProps<"/dashboard">) {
  const { metrics, previous, query, instanceIds, instances, users } =
    await loadMetricsPage(await props.searchParams, { withPrevious: true });

  return (
    <div className="flex flex-col gap-4">
      <MetricsPageHeader
        title="Dashboard"
        metrics={metrics}
        instances={instances}
        users={users}
      />
      <WatchtimeView
        metrics={metrics}
        previous={previous}
        query={query}
        instanceIds={instanceIds}
      />
    </div>
  );
}
