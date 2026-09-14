import { StatTile } from "@/components/charts/stat-tile";
import { TitleLeaderboard } from "@/components/title-leaderboard";
import { formatCount, formatDuration } from "@/lib/format";
import type { MediaMetrics } from "@/lib/types";

export function MoviesView({ metrics, query }: { metrics: MediaMetrics; query: string }) {
  // The bucket keys are fixed by the store's CASE expression
  // (brein/store/metrics_library.py:129); an absent key means no film played.
  const movieSeconds = metrics.watch_time_by_media_type.Movie ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-3">
        <StatTile
          label="Movies watched"
          value={formatCount(metrics.total_watched_movies)}
        />
        <StatTile label="Movie watch time" value={formatDuration(movieSeconds)} />
      </div>

      <TitleLeaderboard
        rows={metrics.watch_time_per_movie}
        title="Watch time per movie"
        emptyLabel="No movies watched in this range."
        drillType="movie"
        query={query}
        timeZone={metrics.app_timezone}
      />
    </div>
  );
}
