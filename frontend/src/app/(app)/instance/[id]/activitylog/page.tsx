import type { Metadata } from "next";
import { DataTable } from "@/components/data-table";
import { Card } from "@/components/ui/card";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { buildQuery, firstParam } from "@/lib/params";
import type { ActivityEntry, ActivityResponse } from "@/lib/types";
import { ActivityFilters } from "./activity-filters";

export const metadata: Metadata = { title: "Activity log" };

export default async function ActivityLogPage(
  props: PageProps<"/instance/[id]/activitylog">,
) {
  const { id } = await props.params;
  const searchParams = await props.searchParams;

  const filters = {
    min_date: firstParam(searchParams.min_date) ?? "",
    max_date: firstParam(searchParams.max_date) ?? "",
    user_id: firstParam(searchParams.user_id) ?? "",
    type: firstParam(searchParams.type) ?? "",
  };

  const result = await softApiFetch<ActivityResponse>(
    `/api/instances/${id}/activity${buildQuery(filters)}`,
  );

  if (!result.ok) {
    return (
      <ApiNotice title="Activity log" status={result.status} message={result.message} />
    );
  }
  if ("supported" in result.data && result.data.supported === false) {
    return (
      <Card title="Activity log">
        <p className="text-sm text-muted">
          This service does not record an activity log.
        </p>
      </Card>
    );
  }

  const data = result.data as Extract<ActivityResponse, { entries: ActivityEntry[] }>;

  return (
    <div className="flex flex-col gap-4">
      {/* Keyed on the filters themselves: the form seeds its state from these
          props once, and in the App Router a search-param navigation re-renders
          this page while keeping the same client instance — so pressing Back
          left the controls showing the filter that had just been undone, and
          Apply re-submitted it. */}
      <ActivityFilters
        key={JSON.stringify(filters)}
        basePath={`/instance/${id}/activitylog`}
        types={data.distinct_types}
        users={data.users}
        current={filters}
      />

      <Card title={`Activity (${data.total})`}>
        <DataTable<ActivityEntry & Record<string, unknown>>
          rows={data.entries as (ActivityEntry & Record<string, unknown>)[]}
          cards
          rowKey={(row, index) => String(row.entry_id ?? index)}
          empty="No activity for these filters."
          columns={[
            {
              key: "date",
              header: "When",
              render: (row) => formatDateTime(row.date),
            },
            { key: "type", header: "Type" },
            { key: "name", header: "Event" },
            {
              key: "user_name",
              header: "User",
              // Resolved server-side from the instance's user list; the log
              // itself stores only a numeric id.
              render: (row) => row.user_name ?? "—",
            },
          ]}
        />
      </Card>
    </div>
  );
}
