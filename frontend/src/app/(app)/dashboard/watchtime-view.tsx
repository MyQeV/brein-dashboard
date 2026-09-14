"use client";

import { useState } from "react";
import { ColumnChart, type ColumnDatum } from "@/components/charts/column-chart";
import {
  RankAvatar,
  RankedBars,
  type RankedDatum,
} from "@/components/charts/ranked-bars";
import { StackedBar, type StackedDatum } from "@/components/charts/stacked-bar";
import { StatTile } from "@/components/charts/stat-tile";
import { DrillModal, type DrillTarget } from "@/components/drill-modal";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { formatCount, formatDuration, weekdayLabel } from "@/lib/format";
import { watchTimePerDay } from "@/lib/per-day";
import { type ApiRow, rowNumber, rowText } from "@/lib/rows";
import type { MediaMetrics } from "@/lib/types";
import { ConcurrencyTile, IdleUsersCard, MostPlayedCard } from "./insights";
import { KpiModal, type KpiTarget } from "./kpi-modal";

/** An em dash rather than a blank label, when no key holds a name. */
const NO_LABEL = "—";

function toRanked(rows: ApiRow[], keys: string[]): RankedDatum[] {
  return rows.map((row) => {
    const label = rowText(row, keys, NO_LABEL);
    return { id: label, label, value: rowNumber(row) };
  });
}

function spanDays(metrics: MediaMetrics): number {
  const start = new Date(`${metrics.start_date}T12:00:00Z`).getTime();
  const end = new Date(`${metrics.end_date}T12:00:00Z`).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return 1;
  return Math.round((end - start) / 86_400_000) + 1;
}

export function WatchtimeView({
  metrics,
  previous,
  query,
  instanceIds,
}: {
  metrics: MediaMetrics;
  /** The window before this one; null when there is nothing to compare with. */
  previous: MediaMetrics | null;
  query: string;
  /** The server filter, so the cards that fetch for themselves can honour it. */
  instanceIds?: string;
}) {
  const [drill, setDrill] = useState<DrillTarget | null>(null);
  const [kpi, setKpi] = useState<KpiTarget | null>(null);

  const multiDay = metrics.start_date !== metrics.end_date;
  const days = spanDays(metrics);
  const deltaLabel = `vs previous ${days === 1 ? "day" : `${days} days`}`;
  const delta = (
    current: number,
    pick: (m: MediaMetrics) => number,
    mode: "percent" | "duration" | "count",
  ) => (previous ? { current, previous: pick(previous), mode } : undefined);

  const byHour: ColumnDatum[] = metrics.streaming_by_hour.map((entry) => ({
    id: String(entry.hour),
    label: `${String(entry.hour).padStart(2, "0")}:00`,
    // Every third hour, or twenty-four labels collide.
    axisLabel: entry.hour % 3 === 0 ? String(entry.hour).padStart(2, "0") : "",
    value: entry.total_seconds,
  }));

  const byWeekday: ColumnDatum[] = metrics.activity_by_weekday.map((entry) => ({
    id: String(entry.weekday),
    label: weekdayLabel(entry.weekday),
    axisLabel: weekdayLabel(entry.weekday).slice(0, 3),
    value: entry.total_seconds,
  }));

  const byMediaType: StackedDatum[] = Object.entries(
    metrics.watch_time_by_media_type,
  ).map(([label, value]) => ({ id: label, label, value }));

  // The row id carries its instance, so the drill can scope to one server:
  // user ids repeat across servers, and Plex account ids are small integers
  // that collide with Emby's. Matches the key `_user_instance_filter` expects.
  const perUser: RankedDatum[] = metrics.watch_time_per_user.map((row, index) => {
    // display_name first, as the filter chips and the KPI modal read it. The
    // API sends both: user_name is the raw name, which may be the bare id,
    // while display_name is normalised to "User {id}" in that case.
    const label = rowText(
      row,
      ["display_name", "user_name", "name", "username", "user_id"],
      NO_LABEL,
    );
    return {
      id: `${rowText(row, ["instance_id"], NO_LABEL)}:${rowText(row, ["user_id"], NO_LABEL)}`,
      label,
      value: rowNumber(row),
      leading: <RankAvatar name={label} highlight={index === 0} />,
    };
  });

  const perSeries = toRanked(metrics.watch_time_per_series, ["label"]);
  const perMovie = toRanked(metrics.watch_time_per_movie, ["label"]);

  const peakHour = byHour.reduce(
    (best, entry) => (entry.value > best.value ? entry : best),
    byHour[0] ?? { id: "", label: "", value: 0 },
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Row 1: the number the page leads with, and when it happens. The
          weekday column only exists when the weekday card does: a one-day
          range dropped the card and left its column as a hole. */}
      <div
        className={cn(
          "grid gap-4 lg:grid-cols-[22.5rem_minmax(0,1fr)]",
          multiDay && "xl:grid-cols-[22.5rem_minmax(0,1fr)_18.75rem]",
        )}
      >
        <StatTile
          hero
          label="Watch time"
          value={formatDuration(metrics.total_watch_time_seconds)}
          delta={delta(
            metrics.total_watch_time_seconds,
            (m) => m.total_watch_time_seconds,
            "percent",
          )}
          deltaLabel={deltaLabel}
          sparkline={
            multiDay
              ? watchTimePerDay(
                  metrics.watch_time_per_user_per_day,
                  metrics.start_date,
                  metrics.end_date,
                )
              : undefined
          }
          onClick={() => setKpi("users")}
        />

        <Card
          title="By hour of day"
          actions={
            peakHour.value > 0 ? (
              <span className="text-xs text-muted">
                Peak <span className="text-text tabular-nums">{peakHour.label}</span>
              </span>
            ) : undefined
          }
        >
          <ColumnChart
            data={byHour}
            format={formatDuration}
            ariaLabel="Watch time by hour of day"
            onColumnClick={(datum) =>
              setDrill({
                drillType: "hour",
                id: datum.id,
                title: `Sessions at ${datum.label}`,
              })
            }
          />
        </Card>

        {/* A one-day range has exactly one weekday: the chart says nothing. */}
        {multiDay && (
          <Card title="By weekday">
            <ColumnChart
              data={byWeekday}
              format={formatDuration}
              ariaLabel="Watch time by weekday"
              onColumnClick={(datum) =>
                setDrill({
                  drillType: "weekday",
                  id: datum.id,
                  title: `Sessions on ${datum.label}`,
                })
              }
            />
          </Card>
        )}
      </div>

      {/* Row 2: the other headline numbers. Each opens its breakdown, as before. */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-4">
        <StatTile
          label="Plays"
          value={formatCount(metrics.total_plays)}
          delta={delta(metrics.total_plays, (m) => m.total_plays, "count")}
          onClick={() => setKpi("users")}
        />
        <StatTile
          label="Average session"
          value={formatDuration(metrics.avg_session_seconds)}
          delta={delta(
            metrics.avg_session_seconds,
            (m) => m.avg_session_seconds,
            "duration",
          )}
          onClick={() => setKpi("avg-session")}
        />
        <StatTile
          label="Active users"
          value={formatCount(metrics.active_users_count)}
          delta={delta(metrics.active_users_count, (m) => m.active_users_count, "count")}
          onClick={() => setKpi("users")}
        />
        <ConcurrencyTile query={query} />
      </div>

      {/* Row 3: who and what. Ranked bars, not doughnuts: the job is magnitude. */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Per user">
          <RankedBars
            data={perUser}
            format={formatDuration}
            onRowClick={(datum) =>
              setDrill({ drillType: "user", id: datum.id, title: datum.label })
            }
          />
        </Card>
        <Card title="Per series">
          <RankedBars
            data={perSeries}
            format={formatDuration}
            emptyLabel="No series watched in this range."
            onRowClick={(datum) =>
              setDrill({ drillType: "series", id: datum.id, title: datum.label })
            }
          />
        </Card>
        <Card title="Per movie">
          <RankedBars
            data={perMovie}
            format={formatDuration}
            emptyLabel="No movies watched in this range."
            footer={`${formatCount(perMovie.length)} ${perMovie.length === 1 ? "movie" : "movies"} in this range`}
            onRowClick={(datum) =>
              setDrill({ drillType: "movie", id: datum.id, title: datum.label })
            }
          />
        </Card>
      </div>

      {/* Row 4: the shape of it, the most replayed, and who has gone quiet. */}
      <div className="grid gap-4 lg:grid-cols-[22.5rem_minmax(0,1fr)_minmax(0,1fr)]">
        <Card title="By media type">
          <div className="flex flex-col gap-4">
            <StackedBar
              data={byMediaType}
              format={formatDuration}
              onSegmentClick={(datum) =>
                setDrill({ drillType: "media_type", id: datum.id, title: datum.label })
              }
            />
            <dl className="grid grid-cols-4 gap-2 border-t border-border pt-3">
              <div className="flex flex-col gap-0.5">
                <dt className="text-[10px] uppercase tracking-wide text-muted">Movies</dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {formatCount(metrics.total_watched_movies)}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-[10px] uppercase tracking-wide text-muted">
                  Episodes
                </dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {formatCount(metrics.total_watched_episodes)}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-[10px] uppercase tracking-wide text-muted">Series</dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {formatCount(metrics.total_watched_series)}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-[10px] uppercase tracking-wide text-muted">
                  Live TV
                </dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {formatCount(metrics.total_watched_live_tv)}
                </dd>
              </div>
            </dl>
          </div>
        </Card>
        <MostPlayedCard rows={metrics.most_watched_items} />
        <IdleUsersCard instanceIds={instanceIds} />
      </div>

      {drill && (
        <DrillModal
          target={drill}
          query={query}
          timeZone={metrics.app_timezone}
          onClose={() => setDrill(null)}
        />
      )}

      {kpi && (
        <KpiModal
          target={kpi}
          metrics={metrics}
          query={query}
          onClose={() => setKpi(null)}
        />
      )}
    </div>
  );
}
