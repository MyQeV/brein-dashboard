import type { Metadata } from "next";
import { apiFetch } from "@/lib/api";
import { buildQuery, firstParam } from "@/lib/params";
import { appTimeZone } from "@/lib/timezone";
import type { MediaMetrics } from "@/lib/types";
import { DateRange } from "../date-range";
import { DailyView } from "./daily-view";

export const metadata: Metadata = { title: "Daily" };

/**
 * Today in the app's zone — the same TZ the API runs on (docker-compose.yml
 * passes it to both).
 */
function today(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: appTimeZone() });
}

function daysBefore(iso: string, days: number): string {
  const value = new Date(`${iso}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}

export default async function DailyPage(props: PageProps<"/dashboard/daily">) {
  const searchParams = await props.searchParams;
  // The old Daily tab defaulted to a week, not to today. Sent explicitly: the
  // API's no-dates fallback is today-7, which is eight inclusive days, while
  // the range bar shows 7d pressed — so clicking 7d dropped the first column.
  const end = firstParam(searchParams.end_date) ?? today();
  const query = buildQuery({
    start_date: firstParam(searchParams.start_date) ?? daysBefore(end, 6),
    end_date: end,
    instance_ids: firstParam(searchParams.instance_ids),
    user_ids: firstParam(searchParams.user_ids),
  });

  const metrics = await apiFetch<MediaMetrics>(`/api/dashboard/media-metrics${query}`);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between">
        <div>
          <h1 className="text-lg font-semibold">Daily</h1>
          <p className="text-sm text-muted">
            {metrics.start_date} to {metrics.end_date} ({metrics.app_timezone})
          </p>
        </div>
        <DateRange startDate={metrics.start_date} endDate={metrics.end_date} />
      </div>
      <DailyView metrics={metrics} />
    </div>
  );
}
