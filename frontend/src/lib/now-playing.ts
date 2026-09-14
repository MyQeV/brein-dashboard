import type { NowPlayingSession } from "@/lib/types";

export type NowPlayingCard = {
  sessionId: string;
  instanceId: string;
  instanceLabel: string;
  title: string;
  episodeLine: string;
  userName: string;
  posterUrl: string;
  playMethod: "transcode" | "direct" | "";
  playMethodLabel: string;
  /**
   * Where the server badge points: the item that is playing when the API
   * could build a link to it, and the server's own web UI otherwise.
   */
  serverUrl: string;
  /** That user's page on the server, empty when there is nowhere to link. */
  userUrl: string;
  progressPct: number;
  /** Position and runtime in seconds; runtime is 0 when the server sends none. */
  positionSeconds: number;
  runtimeSeconds: number;
  isPaused: boolean;
};

/** .NET ticks are 100-nanosecond units, which is what both servers report. */
const TICKS_PER_SECOND = 10_000_000;

/**
 * Shape one session for display.
 *
 * This logic existed twice — in Python for the Jinja fragment and in JS for
 * the live updates — and the JS copy was the one that actually drove the page.
 * One implementation now, used for both the initial render and the socket.
 */
export function toCard(session: NowPlayingSession): NowPlayingCard {
  const item = session.item ?? {};
  const runTicks = Number(item.run_time_ticks ?? 0);
  const positionTicks = Number(session.position_ticks ?? 0);
  const progressPct =
    runTicks > 0 ? Math.min(100, Math.round((100 * positionTicks) / runTicks)) : 0;

  const title = (item.series_name || item.name || "—").trim();
  const parentIndex = item.parent_index_number;
  const index = item.index_number;

  let episodeLine = "";
  if (
    parentIndex !== null &&
    parentIndex !== undefined &&
    index !== null &&
    index !== undefined
  ) {
    episodeLine = `S${parentIndex}E${index} — ${(item.name || "—").trim()}`;
  } else if (item.series_name && !item.name) {
    episodeLine = item.series_name.trim();
  }

  // Prefer the series poster for an episode, falling back to the item's own.
  const seriesId = item.series_id;
  const usesSeriesImage = Boolean(
    seriesId &&
      (parentIndex !== null && parentIndex !== undefined ? true : item.series_name),
  );
  const imageItemId = usesSeriesImage ? seriesId : item.id;
  const imageTag = usesSeriesImage ? "" : (item.image_tag ?? "");

  const instanceId = String(session.instance_id ?? "");
  const posterUrl = imageItemId
    ? `/api/instances/${encodeURIComponent(instanceId)}/image` +
      `?item_id=${encodeURIComponent(String(imageItemId))}` +
      `&tag=${encodeURIComponent(String(imageTag))}&type=Primary`
    : "";

  const appUrl = (session.app_url ?? "").replace(/\/+$/, "");
  const serviceType = (session.service_type ?? "").toLowerCase();
  const userId = (session.user_id ?? "").trim();
  // Routes taken from each server's own UI rather than assumed: Emby keeps
  // the profile under a hash-bang at #!/users/user, while Jellyfin dropped
  // both the bang and the .html and moved it under the dashboard. Plex has no
  // per-user page on the server at all — its accounts live on plex.tv — so
  // its badge stays plain text.
  const userUrl =
    appUrl && userId && serviceType === "emby"
      ? `${appUrl}/web/index.html#!/users/user?userId=${encodeURIComponent(userId)}`
      : appUrl && userId && serviceType === "jellyfin"
        ? `${appUrl}/web/index.html#/dashboard/users/profile?userId=${encodeURIComponent(userId)}`
        : "";

  const method = (session.play_method ?? "").trim();
  const playMethod =
    method === "Transcode"
      ? "transcode"
      : method === "DirectStream" || method === "DirectPlay"
        ? "direct"
        : "";

  return {
    // item_url is the deep link the API already builds per backend; it falls
    // back to the base URL itself when the session carries no item id, so
    // there is nothing to check beyond it being set.
    serverUrl: (session.item_url ?? "").trim() || appUrl,
    userUrl,
    positionSeconds: positionTicks > 0 ? positionTicks / TICKS_PER_SECOND : 0,
    runtimeSeconds: runTicks > 0 ? runTicks / TICKS_PER_SECOND : 0,
    sessionId: session.session_id ?? "",
    instanceId,
    instanceLabel: String(session.instance_label ?? session.instance_id ?? "").trim(),
    title,
    episodeLine,
    userName: (session.user_name ?? "—").trim(),
    posterUrl,
    playMethod,
    playMethodLabel:
      playMethod === "transcode"
        ? "Transcoding"
        : playMethod === "direct"
          ? "Direct play"
          : "",
    progressPct,
    isPaused: Boolean(session.is_paused),
  };
}
