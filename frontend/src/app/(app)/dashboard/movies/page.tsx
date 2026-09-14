import type { Metadata } from "next";
import { loadMetricsPage, MetricsPageHeader } from "../metrics-page";
import { MoviesView } from "./movies-view";

export const metadata: Metadata = { title: "Movies" };

export default async function MoviesPage(props: PageProps<"/dashboard/movies">) {
  const { metrics, query, instances, users } = await loadMetricsPage(
    await props.searchParams,
  );

  return (
    <div className="flex flex-col gap-4">
      <MetricsPageHeader
        title="Movies"
        metrics={metrics}
        instances={instances}
        users={users}
      />
      <MoviesView metrics={metrics} query={query} />
    </div>
  );
}
