import { StatTile } from "@/components/charts/stat-tile";
import { TitleLeaderboard } from "@/components/title-leaderboard";
import { formatCount, formatDuration } from "@/lib/format";
import type { MediaMetrics } from "@/lib/types";

export function SeriesView({ metrics, query }: { metrics: MediaMetrics; query: string }) {
  // The bucket keys are fixed by the store's CASE expression
  // (brein/store/metrics_library.py:130); an absent key means nothing played.
  const episodeSeconds = metrics.watch_time_by_media_type.Episode ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-3">
        <StatTile
          label="Series watched"
          value={formatCount(metrics.total_watched_series)}
        />
        <StatTile label="Episode watch time" value={formatDuration(episodeSeconds)} />
      </div>

      <TitleLeaderboard
        rows={metrics.watch_time_per_series}
        title="Watch time per series"
        emptyLabel="No series watched in this range."
        drillType="series"
        query={query}
        timeZone={metrics.app_timezone}
      />
    </div>
  );
}
