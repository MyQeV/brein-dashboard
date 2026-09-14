import type { Metadata } from "next";
import { StatTile } from "@/components/charts/stat-tile";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { DownloadTotals } from "@/lib/types";
import { DownloadsDailyChart } from "./daily-chart";

export const metadata: Metadata = { title: "Downloads" };

export default async function DownloadsPage() {
  const { downloads } = await apiFetch<{ downloads: DownloadTotals[] }>(
    "/api/dashboard/downloads",
  );

  if (downloads.length === 0) {
    return (
      <Card title="Downloads">
        <p className="text-sm text-muted">
          No configured SABnzbd instance. Add one under Settings → App.
        </p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {downloads.map((entry) => (
        <section key={entry.instance_id} className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">
            {entry.label}
            <span className="ml-2 font-normal text-muted">
              {entry.collected_at
                ? `updated ${formatDateTime(entry.collected_at)}`
                : "no statistics collected yet"}
            </span>
          </h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
            {/* Totals come from the API as raw bytes; formatting is ours. */}
            <StatTile label="Today" value={formatBytes(entry.bytes_today ?? 0)} />
            <StatTile label="This week" value={formatBytes(entry.bytes_week ?? 0)} />
            <StatTile label="This month" value={formatBytes(entry.bytes_month ?? 0)} />
            <StatTile label="All time" value={formatBytes(entry.bytes_total ?? 0)} />
          </div>
          <DownloadsDailyChart instanceId={entry.instance_id} />
        </section>
      ))}
    </div>
  );
}
