"use client";

import { useState } from "react";
import { BarChart } from "@/components/charts/bar-chart";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useApi } from "@/lib/use-api";

const RANGES = [7, 30, 90] as const;

type Series = { labels: string[]; gigabytes: number[] };

function formatGigabytes(value: number): string {
  return `${value < 10 ? value.toFixed(2) : Math.round(value)} GB`;
}

/**
 * The per-day volume SABnzbd itself keeps, read back from the stored
 * `server_stats` snapshots — the chart the old downloads tab drew.
 */
export function DownloadsDailyChart({ instanceId }: { instanceId: number }) {
  const [days, setDays] = useState<number>(30);
  // useApi aborts the previous request, so a slow response for the range the
  // user just left cannot overwrite the one they chose.
  const state = useApi<Series>(
    `/api/dashboard/downloads-daily?instance_id=${instanceId}&days=${days}`,
  );

  const rangeControl = (
    <fieldset className="flex gap-1 border-0 p-0">
      <legend className="sr-only">Range</legend>
      {RANGES.map((option) => (
        <Button
          key={option}
          size="sm"
          variant={days === option ? "primary" : "ghost"}
          aria-pressed={days === option}
          onClick={() => setDays(option)}
        >
          {option}d
        </Button>
      ))}
    </fieldset>
  );

  const data =
    state.status === "ok"
      ? state.data.labels.map((label, index) => ({
          label: label.slice(5),
          // Only every third tick is drawn, or the labels collide at 90 days.
          sublabel: index % 3 === 0 ? label.slice(5) : "",
          value: state.data.gigabytes[index] ?? 0,
        }))
      : [];

  return (
    <Card title="Downloaded per day" actions={rangeControl}>
      {state.status === "loading" && <Spinner label="Loading history…" />}

      {state.status === "error" && (
        <p className="text-sm text-error" role="alert">
          {state.message}
        </p>
      )}

      {state.status === "ok" && (
        <BarChart
          data={data}
          format={formatGigabytes}
          emptyLabel="No download history recorded yet."
        />
      )}
    </Card>
  );
}
