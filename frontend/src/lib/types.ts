/** Wire types for the brein API. Field names match the JSON exactly. */

export type User = {
  id: string;
  username: string;
  email: string | null;
  full_name: string | null;
  disabled: boolean;
  is_admin: boolean;
  role: string;
};

export type Tab = { slug: string; label: string; admin_only: boolean };

/** GET /api/service-types — one entry per registered service type. */
export type ServiceType = {
  id: string;
  name: string;
  category: string;
  default_port: number | null;
  icon: boolean;
  tabs: Tab[];
  arr_tables: Record<string, unknown> | null;
};

/** GET /api/instances/{id} — the edit form's shape. */
export type InstanceDetail = {
  id: number;
  service_type: string;
  label: string | null;
  host: string;
  port: number | null;
  external_url: string;
  active: boolean;
  sort_order: number;
  media_server_id: string;
  is_configured: boolean;
  app_url: string;
  /** Masked, never the real key. Send null to keep the stored one. */
  api_key_masked: string;
};

export type Instance = {
  id: number;
  service_type: string;
  label: string | null;
  category: string | null;
  is_configured: boolean;
  active: boolean;
  sort_order: number;
  app_url?: string | null;
  service_name?: string | null;
};

/** GET /api/calendar — sorted by (date, title). */
export type CalendarEvent = {
  date: string;
  type: "episode" | "movie";
  title: string;
  subtitle: string | null;
  source: "sonarr" | "radarr";
  instance_id: number;
  instance_label: string;
  has_file: boolean;
  monitored: boolean;
  poster_url: string | null;
  overview: string | null;
  runtime: number | null;
  year: number | null;
  genres: string[] | null;
  season_number?: number | null;
  episode_number?: number | null;
  episode_title?: string | null;
  /** Where to open this in the app that manages it. */
  instance_base_url?: string | null;
  /** Sonarr's route key. */
  title_slug?: string | null;
  /** Radarr's route key. */
  tmdb_id?: number | string | null;
};

/** GET /api/dashboard/media-metrics */
export type MediaMetrics = {
  start_date: string;
  end_date: string;
  total_plays: number;
  total_watch_time_seconds: number;
  avg_session_seconds: number;
  active_users_count: number;
  plays_per_user: Record<string, unknown>[];
  watch_time_per_user: Record<string, unknown>[];
  /** Merged across Emby, Jellyfin and Plex by the API; see dashboard.py:458. */
  watch_time_per_series: Record<string, unknown>[];
  /** Merged across Emby, Jellyfin and Plex by the API; see dashboard.py:465. */
  watch_time_per_movie: Record<string, unknown>[];
  most_watched_items: Record<string, unknown>[];
  total_watched_movies: number;
  total_watched_episodes: number;
  total_watched_series: number;
  total_watched_live_tv: number;
  watch_time_by_media_type: Record<string, number>;
  streaming_by_hour: { hour: number; total_seconds: number }[];
  activity_by_weekday: { weekday: number; total_seconds: number }[];
  watch_time_per_user_per_day: unknown[];
  /** Timestamps are formatted in this zone, not the browser's. */
  app_timezone: string;
};

/** GET /api/instances/{id}/users — Emby and Jellyfin only. */
export type MediaUser = {
  id: string;
  name: string;
  is_disabled: boolean;
  is_administrator: boolean;
  enable_all_folders: boolean;
  enabled_folder_ids: string[];
  last_login_date: string | null;
  last_activity_date: string | null;
  primary_image_tag: string | null;
  user_item_id: string | null;
  enable_live_tv: boolean;
  max_simultaneous_streams: number;
};

export type MediaLibrary = {
  /** The id a user policy references — Emby's Guid, Jellyfin's own Id. */
  id: string;
  /** The server's internal id, which on Emby is a different number. */
  internal_id?: string;
  name: string;
  server_id?: string | null;
  guid?: string | null;
  type?: string | null;
  collection_type?: string | null;
};

export type MediaUsersResponse =
  | { supported: false }
  | { supported?: true; users: MediaUser[]; libraries: MediaLibrary[] };

/** GET /api/users — the admin user list. */
export type AdminUser = {
  id: string;
  username: string;
  email: string | null;
  full_name: string | null;
  disabled: boolean;
  is_admin: boolean;
  role: string;
  created_at: number | null;
  last_login_at: number | null;
  last_failed_login_at: number | null;
  failed_login_attempts: number;
  last_login_ip: string | null;
};

/** GET /api/settings/system */
export type SystemSetting = {
  key: string;
  attr: string;
  label: string;
  value_type: "int" | "float" | "str";
  default: number | string;
  unit?: string;
  description?: string;
  current: number | string;
};

/** One session from GET /api/now-playing and the /ws/now-playing feed. */
export type NowPlayingSession = {
  session_id: string;
  instance_id: number | string | null;
  instance_label?: string | null;
  service_type?: string | null;
  /** The instance's external URL, when one is configured. */
  app_url?: string | null;
  user_id?: string | null;
  user_name?: string | null;
  is_paused?: boolean;
  position_ticks?: number | null;
  play_method?: string | null;
  item_url?: string | null;
  item?: {
    id?: string | null;
    name?: string | null;
    series_name?: string | null;
    series_id?: string | null;
    index_number?: number | null;
    parent_index_number?: number | null;
    run_time_ticks?: number | null;
    image_tag?: string | null;
  } | null;
};

/** GET /api/dashboard/downloads — raw bytes; the client formats them. */
export type DownloadTotals = {
  instance_id: number;
  label: string;
  collected_at: string | null;
  bytes_today: number | null;
  bytes_week: number | null;
  bytes_month: number | null;
  bytes_total: number | null;
};

/** GET /api/tasks */
export type ScheduledTask = {
  id: number;
  key: string;
  name: string;
  category: string | null;
  instance_id: number | null;
  instance_label: string | null;
  instance_service_type: string | null;
  instance_active: boolean | null;
  interval_seconds: number;
  enabled: boolean;
  is_running: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_duration_ms: number | null;
  next_due_at: string | null;
};

export type TaskRun = {
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  status: string | null;
  error_message: string | null;
};

/** GET /api/instances/{id}/activity */
export type ActivityEntry = {
  entry_id?: number;
  date: string | null;
  name?: string | null;
  type?: string | null;
  user_id?: number | string | null;
  user_name?: string | null;
  overview?: string | null;
  item_id?: string | null;
};

export type ActivityResponse =
  | { supported: false }
  | {
      entries: ActivityEntry[];
      distinct_types: string[];
      users: { id: string; name: string }[];
      total: number;
    };

/** GET /api/instances/{id}/user-dashboard */
export type UserDashboard =
  | { supported: false }
  | {
      users: { id: string; name: string }[];
      selected_user_id: string | null;
      selected_user_name?: string;
      start: string;
      end: string;
      today: string;
      stats: {
        plays: number;
        watch_seconds: number;
        last_activity: string | null;
        longest_session: Record<string, unknown> | null;
        top_weekday: Record<string, unknown> | null;
        daily: Record<string, unknown>[];
        recent_items: Record<string, unknown>[];
        top_series: Record<string, unknown>[];
        top_movies: Record<string, unknown>[];
        watch_by_type: Record<string, unknown>[];
      } | null;
    };

/** GET /api/instances/{id}/downloads/queue — normalized across all three clients. */
export type DownloadItem = {
  id: string;
  name: string;
  status: string;
  size_bytes: number;
  remaining_bytes: number;
  progress_pct: number;
  eta: string | number | null;
  category: string | null;
};

/** What the instance's download client can do; carried on /queue and /history. */
export type DownloadCapabilities = {
  per_item_pause: boolean;
  queue_level_pause: boolean;
  history: "list" | "none";
};

export type DownloadQueue = {
  service_type: string;
  capabilities: DownloadCapabilities;
  items: DownloadItem[];
  paused: boolean;
  /** SABnzbd only; the others limit by rate. */
  speed_limit_pct: number | null;
  speed_limit_bytes: number;
  speed_bytes: number;
  pause_seconds_left: number;
};

export type DownloadHistoryItem = {
  id: string;
  name: string;
  status: string;
  size_bytes: number;
  completed_at: string | number | null;
  category: string | null;
  error: string | null;
};

/** GET /api/dashboard/media-drill — one play session. */
export type MediaDrillRow = Record<string, unknown>;

/** GET /api/dashboard/user-sessions — one session for one user on one day. */
export type UserSessionRow = Record<string, unknown>;
