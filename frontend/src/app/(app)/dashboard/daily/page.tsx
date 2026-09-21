import type { Metadata } from "next";
import { apiFetch } from "@/lib/api";
import { parsePeriod, periodToDate, todayIn } from "@/lib/calendar-range";
import { buildQuery, firstParam } from "@/lib/params";
import { appTimeZone } from "@/lib/timezone";
import type { MediaMetrics } from "@/lib/types";
import { DateRange } from "../date-range";
import { DailyView } from "./daily-view";

export const metadata: Metadata = { title: "Daily" };

export default async function DailyPage(props: PageProps<"/dashboard/daily">) {
  const searchParams = await props.searchParams;
  // The Daily tab opens on a week, not on today. Sent explicitly, and as the
  // same Monday-to-today range the "Week" preset sends, so the preset shows
  // pressed and clicking it changes nothing. Today is taken in the app's
  // zone — the same TZ the API runs on (docker-compose.yml passes it to both).
  const startDate = firstParam(searchParams.start_date);
  const endDate = firstParam(searchParams.end_date);
  const week = periodToDate("week", todayIn(appTimeZone()));
  // On a Monday the week so far is one day, which the dates alone would
  // call "Today": the default is a week and says so.
  const period =
    startDate || endDate ? parsePeriod(firstParam(searchParams.period)) : "week";
  const query = buildQuery({
    start_date: startDate ?? week.start,
    end_date: endDate ?? week.end,
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
        <DateRange
          startDate={metrics.start_date}
          endDate={metrics.end_date}
          period={period}
        />
      </div>
      <DailyView metrics={metrics} />
    </div>
  );
}
