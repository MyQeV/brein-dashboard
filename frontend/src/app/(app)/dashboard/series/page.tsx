import type { Metadata } from "next";
import { loadMetricsPage, MetricsPageHeader } from "../metrics-page";
import { SeriesView } from "./series-view";

export const metadata: Metadata = { title: "Series" };

export default async function SeriesPage(props: PageProps<"/dashboard/series">) {
  const { metrics, query, instances, users } = await loadMetricsPage(
    await props.searchParams,
  );

  return (
    <div className="flex flex-col gap-4">
      <MetricsPageHeader
        title="Series"
        metrics={metrics}
        instances={instances}
        users={users}
      />
      <SeriesView metrics={metrics} query={query} />
    </div>
  );
}
