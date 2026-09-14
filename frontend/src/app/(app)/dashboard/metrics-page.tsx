import { apiFetch, softApiFetch } from "@/lib/api";
import { buildQuery, firstParam, type SearchParams } from "@/lib/params";
import { previousRange } from "@/lib/previous-range";
import { rowText } from "@/lib/rows";
import type { Instance, MediaMetrics } from "@/lib/types";
import { DateRange } from "./date-range";
import { InstanceFilter } from "./instance-filter";
import { UserFilter } from "./user-filter";

/**
 * The preamble shared by the metric tabs (Watch time, Movies, Series).
 *
 * All three read the same endpoint over the same filters and render the same
 * header and filter row; only the heading and the view below differ. Three
 * copies meant every filter fix — media servers only, the compound user key,
 * the unfiltered picker — had to be made three times, and the Watch time tab
 * was usually the only one that got it.
 */

/** The services that record playback; everything else has no watch time. */
const MEDIA_SERVER_TYPES = new Set(["emby", "jellyfin", "plex"]);

/**
 * Today in the app's zone — the same `TZ` the API runs on (docker-compose.yml
 * passes it to both). Without dates the API falls back to a week, but these
 * tabs open on today.
 */
function today(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: process.env.TZ || "UTC" });
}

export type MetricsPageData = {
  metrics: MediaMetrics;
  /** The window before this one, for the deltas; null when it cannot be compared. */
  previous: MediaMetrics | null;
  /** The filter query string, for the drill-downs to reuse. */
  query: string;
  /** The current server filter, for cards that fetch for themselves. */
  instanceIds?: string;
  instances: { id: number; label: string }[];
  users: { id: string; name: string }[];
};

export async function loadMetricsPage(
  searchParams: SearchParams,
  options: { withPrevious?: boolean } = {},
): Promise<MetricsPageData> {
  const startDate = firstParam(searchParams.start_date) ?? today();
  const endDate = firstParam(searchParams.end_date) ?? today();
  const instanceIds = firstParam(searchParams.instance_ids);
  const userIds = firstParam(searchParams.user_ids);

  const query = buildQuery({
    start_date: startDate,
    end_date: endDate,
    instance_ids: instanceIds,
    user_ids: userIds,
  });

  // The same span, ending the day before. Soft: a failed comparison fetch
  // must not take the page down with it.
  const before = options.withPrevious ? previousRange(startDate, endDate) : null;
  const [metrics, previousResult] = await Promise.all([
    apiFetch<MediaMetrics>(`/api/dashboard/media-metrics${query}`),
    before
      ? softApiFetch<MediaMetrics>(
          `/api/dashboard/media-metrics${buildQuery({
            start_date: before.start,
            end_date: before.end,
            instance_ids: instanceIds,
            user_ids: userIds,
          })}`,
        )
      : Promise.resolve(null),
  ]);
  const previous = previousResult?.ok ? previousResult.data : null;

  // The picker must list everyone, not just whoever survived the current
  // filter — otherwise selecting a user makes every other user unselectable.
  const pickerMetrics = userIds
    ? await apiFetch<MediaMetrics>(
        `/api/dashboard/media-metrics${buildQuery({
          start_date: startDate,
          end_date: endDate,
          instance_ids: instanceIds,
        })}`,
      )
    : metrics;

  const instancesResult = await softApiFetch<{ instances: Instance[] } | Instance[]>(
    "/api/instances",
  );
  const instanceRows = instancesResult.ok
    ? Array.isArray(instancesResult.data)
      ? instancesResult.data
      : (instancesResult.data.instances ?? [])
    : [];
  // Only media servers report playback; Sonarr, Radarr and the rest have no
  // watch time to filter by, so they never belonged in this row.
  const instances = instanceRows
    .filter((row) => MEDIA_SERVER_TYPES.has((row.service_type ?? "").toLowerCase()))
    .map((row) => ({ id: row.id, label: row.label ?? `Instance ${row.id}` }));

  // Rows carry a bare numeric user_id that can collide across servers, so the
  // filter option id is the compound "instance_id:user_id" key the backend's
  // `_user_instance_filter` expects — a bare user_id is silently ignored.
  const users = pickerMetrics.watch_time_per_user
    .map((row) => {
      const instanceId = row.instance_id;
      const userId = row.user_id;
      const hasInstanceId =
        typeof instanceId === "number" || typeof instanceId === "string";
      const hasUserId =
        (typeof userId === "string" || typeof userId === "number") &&
        String(userId) !== "";
      if (!hasInstanceId || !hasUserId) return null;

      return {
        id: `${instanceId}:${userId}`,
        name: rowText(row, ["display_name", "user_name"], String(userId)),
      };
    })
    .filter((user): user is { id: string; name: string } => user !== null);

  return { metrics, previous, query, instanceIds, instances, users };
}

/** Title, resolved range and the filter controls, above whichever view follows. */
export function MetricsPageHeader({
  title,
  metrics,
  instances,
  users,
}: {
  title: string;
} & Pick<MetricsPageData, "metrics" | "instances" | "users">) {
  return (
    <>
      <div className="flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between">
        <div>
          <h1 className="text-lg font-semibold">{title}</h1>
          <p className="text-sm text-muted">
            {metrics.start_date} to {metrics.end_date} ({metrics.app_timezone})
          </p>
        </div>
        <DateRange startDate={metrics.start_date} endDate={metrics.end_date} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <InstanceFilter instances={instances} />
        <UserFilter users={users} />
      </div>
    </>
  );
}
