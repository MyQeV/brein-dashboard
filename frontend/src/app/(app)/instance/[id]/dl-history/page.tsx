import type { Metadata } from "next";
import { DataTable } from "@/components/data-table";
import { Card } from "@/components/ui/card";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { DownloadCapabilities, DownloadHistoryItem } from "@/lib/types";
import { MarkCompletedButton, RetryAllButton } from "./history-actions";

export const metadata: Metadata = { title: "History" };

/** Completion is an epoch on SABnzbd and the other usenet clients, not an ISO string. */
function completed(value: string | number | null): string {
  if (value === null || value === "") return "—";
  if (typeof value === "number") {
    return formatDateTime(new Date(value * 1000).toISOString());
  }
  return formatDateTime(value);
}

export default async function DownloadHistoryPage(
  props: PageProps<"/instance/[id]/dl-history">,
) {
  const { id } = await props.params;
  const result = await softApiFetch<{
    service_type: string;
    capabilities: DownloadCapabilities;
    items: DownloadHistoryItem[];
  }>(`/api/instances/${id}/downloads/history`);

  if (!result.ok) {
    return <ApiNotice title="History" status={result.status} message={result.message} />;
  }

  const { capabilities, items } = result.data;
  const noHistory = capabilities.history === "none";
  // The downloader spells failure differently per backend, so match on the
  // error field first and fall back to the status word.
  const failedCount = items.filter(
    (item) => item.error || item.status?.toLowerCase() === "failed",
  ).length;

  return (
    <Card
      title={`History (${items.length})`}
      actions={
        noHistory ? undefined : (
          <RetryAllButton instanceId={Number(id)} failedCount={failedCount} />
        )
      }
    >
      {noHistory ? (
        <p className="text-sm text-muted">
          This client keeps no separate history — completed downloads stay in the queue.
        </p>
      ) : (
        <DataTable<DownloadHistoryItem & Record<string, unknown>>
          rows={items as (DownloadHistoryItem & Record<string, unknown>)[]}
          cards
          rowKey={(row, index) => row.id || String(index)}
          empty="No completed downloads."
          columns={[
            { key: "name", header: "Name" },
            {
              key: "status",
              header: "Status",
              render: (row) => (
                <span
                  className={row.error ? "text-error" : undefined}
                  title={row.error ?? undefined}
                >
                  {row.status}
                </span>
              ),
            },
            {
              key: "size_bytes",
              header: "Size",
              align: "right",
              render: (row) => formatBytes(row.size_bytes),
            },
            {
              key: "completed_at",
              header: "Completed",
              render: (row) => completed(row.completed_at),
            },
            {
              key: "actions",
              header: "",
              align: "right",
              // Only a failed item can be marked done; the rest already are.
              render: (row) =>
                row.error || row.status?.toLowerCase() === "failed" ? (
                  <MarkCompletedButton instanceId={Number(id)} itemId={row.id} />
                ) : null,
            },
          ]}
        />
      )}
    </Card>
  );
}
