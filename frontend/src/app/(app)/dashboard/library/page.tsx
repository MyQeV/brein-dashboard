import type { Metadata } from "next";
import { StatTile } from "@/components/charts/stat-tile";
import { DataTable } from "@/components/data-table";
import { Card } from "@/components/ui/card";
import { apiFetch, softApiFetch } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { buildQuery, firstParam } from "@/lib/params";
import type { Instance } from "@/lib/types";
import { InstanceFilter } from "../instance-filter";
import { UnwatchedItems } from "./unwatched-items";

export const metadata: Metadata = { title: "Library" };

/** The services that record playback; nothing else can mark an item watched. */
const MEDIA_SERVER_TYPES = new Set(["emby", "jellyfin", "plex"]);

/** One row of `summary` from GET /api/dashboard/library-unwatched. */
type UnwatchedSummary = {
  instance_id: number;
  instance_label: string;
  item_type: string;
  total: number;
  unwatched: number;
};

/** Share of the library somebody has played at least once. */
function playedPercent(total: number, unwatched: number): string {
  if (total <= 0) return "—";
  return `${(((total - unwatched) / total) * 100).toFixed(1)}%`;
}

export default async function LibraryPage(props: PageProps<"/dashboard/library">) {
  const searchParams = await props.searchParams;
  const instanceIds = firstParam(searchParams.instance_ids);
  const query = buildQuery({ instance_ids: instanceIds });

  // `items` is only populated when an item_type is passed, so this server read
  // is the summary alone; the titles are fetched per type by the client below.
  const { summary } = await apiFetch<{ summary: UnwatchedSummary[] }>(
    `/api/dashboard/library-unwatched${query}`,
  );

  const instancesResult = await softApiFetch<{ instances: Instance[] } | Instance[]>(
    "/api/instances",
  );
  const instanceRows = instancesResult.ok
    ? Array.isArray(instancesResult.data)
      ? instancesResult.data
      : (instancesResult.data.instances ?? [])
    : [];
  const instances = instanceRows
    .filter((row) => MEDIA_SERVER_TYPES.has((row.service_type ?? "").toLowerCase()))
    .map((row) => ({ id: row.id, label: row.label ?? `Instance ${row.id}` }));

  const total = summary.reduce((sum, row) => sum + row.total, 0);
  const unwatched = summary.reduce((sum, row) => sum + row.unwatched, 0);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">Library</h1>
        <p className="text-sm text-muted">Movies and episodes nobody has ever played.</p>
      </div>

      <InstanceFilter instances={instances} />

      {summary.length === 0 ? (
        <Card title="Library">
          <p className="text-sm text-muted">
            No synced library items. Add a media server under Settings → App, then let the
            items sync task run.
          </p>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
            <StatTile
              label="Items"
              value={formatCount(total)}
              hint="movies and episodes"
            />
            <StatTile label="Never played" value={formatCount(unwatched)} />
            <StatTile label="Played" value={playedPercent(total, unwatched)} />
          </div>

          <Card title="By server and type">
            <DataTable<UnwatchedSummary>
              rows={summary}
              cards
              rowKey={(row) => `${row.instance_id}:${row.item_type}`}
              empty="Nothing synced yet."
              columns={[
                {
                  key: "instance_label",
                  header: "Server",
                  render: (row) => row.instance_label || `Instance ${row.instance_id}`,
                },
                { key: "item_type", header: "Type" },
                {
                  key: "total",
                  header: "Total",
                  align: "right",
                  render: (row) => formatCount(row.total),
                },
                {
                  key: "unwatched",
                  header: "Never played",
                  align: "right",
                  render: (row) => formatCount(row.unwatched),
                },
                {
                  key: "played_pct",
                  header: "Played",
                  align: "right",
                  render: (row) => playedPercent(row.total, row.unwatched),
                },
              ]}
            />
          </Card>

          <UnwatchedItems instanceIds={instanceIds} />
        </>
      )}
    </div>
  );
}
