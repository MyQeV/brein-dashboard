import type { Metadata } from "next";
import { BarChart } from "@/components/charts/bar-chart";
import { StatTile } from "@/components/charts/stat-tile";
import { DataTable } from "@/components/data-table";
import { Card } from "@/components/ui/card";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import { formatCount, formatDateTime, formatDuration, readPath } from "@/lib/format";
import { buildQuery, firstParam } from "@/lib/params";
import { rowNumber, rowText } from "@/lib/rows";
import { appTimeZone } from "@/lib/timezone";
import type { UserDashboard } from "@/lib/types";
import { UserPicker } from "./user-picker";

export const metadata: Metadata = { title: "User dashboard" };

export default async function UserDashboardPage(
  props: PageProps<"/instance/[id]/user-dashboard">,
) {
  const { id } = await props.params;
  const searchParams = await props.searchParams;

  const query = {
    user_id: firstParam(searchParams.user_id) ?? "",
    start: firstParam(searchParams.start) ?? "",
    end: firstParam(searchParams.end) ?? "",
  };

  const result = await softApiFetch<UserDashboard>(
    `/api/instances/${id}/user-dashboard${buildQuery(query)}`,
  );
  if (!result.ok) {
    return (
      <ApiNotice title="User dashboard" status={result.status} message={result.message} />
    );
  }
  if ("supported" in result.data && result.data.supported === false) {
    return (
      <Card title="User dashboard">
        <p className="text-sm text-muted">
          Per-user statistics are only available for Emby instances.
        </p>
      </Card>
    );
  }

  const data = result.data as Exclude<UserDashboard, { supported: false }>;
  const basePath = `/instance/${id}/user-dashboard`;
  const lastActivity = data.stats?.last_activity
    ? formatDateTime(data.stats.last_activity, appTimeZone()).split(", ")
    : [];

  return (
    <div className="flex flex-col gap-4">
      {/* Keyed on the selection, for the reason the activity filters are:
          the picker seeds from these props once, so Back left it naming a
          user whose statistics were no longer on screen. */}
      <UserPicker
        key={`${data.selected_user_id ?? ""}:${data.start}:${data.end}`}
        basePath={basePath}
        users={data.users}
        selectedUserId={data.selected_user_id}
        start={data.start}
        end={data.end}
      />

      {!data.stats ? (
        <Card>
          <p className="text-sm text-muted">
            Choose a user to see their statistics for this range.
          </p>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-3">
            <StatTile label="Plays" value={formatCount(data.stats.plays)} />
            <StatTile
              label="Watch time"
              value={formatDuration(data.stats.watch_seconds)}
            />
            <StatTile
              label="Last activity"
              // Date as the number, time as the hint: "14/09/2026, 20:27" in
              // the tile's large type wrapped mid-string on a phone.
              value={lastActivity[0] ?? "Never"}
              hint={lastActivity[1]}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Watch time per day">
              <BarChart
                data={data.stats.daily.map((row) => ({
                  label: rowText(row, ["stat_date"], "—"),
                  sublabel: rowText(row, ["stat_date"], "—").slice(5),
                  value: rowNumber(row, ["watch_time_seconds"]),
                }))}
                format={formatDuration}
              />
            </Card>

            <Card title="Watch time by type">
              <BarChart
                orientation="horizontal"
                data={data.stats.watch_by_type.map((row) => ({
                  label: rowText(row, ["item_type"], "—"),
                  value: rowNumber(row, ["total_seconds"]),
                }))}
                format={formatDuration}
              />
            </Card>

            {/* Keyed on the store's `group_key` (the series or item id): the
                label is "Unknown series" for every series whose parent has
                not synced, and repeated keys would drop bars. */}
            <Card title="Top series">
              <BarChart
                orientation="horizontal"
                data={data.stats.top_series.slice(0, 10).map((row) => ({
                  id: rowText(row, ["group_key"]) || undefined,
                  label: rowText(row, ["display_name"], "—"),
                  value: rowNumber(row, ["total_seconds"]),
                }))}
                format={formatDuration}
                emptyLabel="No series watched in this range."
              />
            </Card>

            <Card title="Top movies">
              <BarChart
                orientation="horizontal"
                data={data.stats.top_movies.slice(0, 10).map((row) => ({
                  id: rowText(row, ["group_key"]) || undefined,
                  label: rowText(row, ["display_name"], "—"),
                  value: rowNumber(row, ["total_seconds"]),
                }))}
                format={formatDuration}
                emptyLabel="No movies watched in this range."
              />
            </Card>
          </div>

          <Card title="Recent activity">
            <DataTable<Record<string, unknown>>
              rows={data.stats.recent_items}
              rowKey={(row, index) => String(readPath(row, "entry_id") ?? index)}
              empty="No recent activity."
              columns={[
                {
                  key: "name",
                  header: "Item",
                  render: (row) => rowText(row, ["item_name", "entry_name"], "—"),
                },
                {
                  key: "type",
                  header: "Type",
                  render: (row) => rowText(row, ["item_type", "entry_type"], "—"),
                },
                {
                  key: "date",
                  header: "When",
                  render: (row) =>
                    formatDateTime(
                      readPath(row, "date") ?? row.last_played,
                      appTimeZone(),
                    ),
                },
              ]}
            />
          </Card>
        </>
      )}
    </div>
  );
}
