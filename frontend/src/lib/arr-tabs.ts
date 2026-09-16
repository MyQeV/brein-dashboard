import { EXTRA_ARR_TABS } from "@/extras";
import { formatBytes, formatDateTime, readPath } from "@/lib/format";
import type { ServiceTypeMap } from "@/lib/service-types";

/**
 * Config for the Sonarr / Radarr list tabs.
 *
 * These endpoints proxy the upstream *arr APIs, so they share a shape:
 * either `{records, page, pageSize, totalRecords}` or a bare array. One
 * generic page renders all of them from this table instead of sixteen
 * near-identical pages. Other services carry the same config in their
 * `arr_tables` from GET /api/service-types.
 */

export type ArrColumn = {
  key: string;
  header: string;
  align?: "left" | "right";
  /** Dotted path into the record, e.g. "series.title". */
  path?: string;
  kind?: "text" | "bytes" | "date" | "boolean";
};

export type ArrTab = {
  /** Path after /api/instances/{id}/{service}/ */
  endpoint: string;
  title: string;
  paged: boolean;
  /**
   * Query name for the page size. Sonarr and Radarr declare `pageSize`;
   * some routers declare `page_size`. Sending the wrong one is silently
   * ignored by FastAPI, so the server pages by its own default while the
   * client pages by ours — and rows get skipped.
   */
  pageSizeParam?: "pageSize" | "page_size";
  columns: ArrColumn[];
  empty?: string;
  /**
   * The bulk delete this tab offers, if any.
   *
   * `endpoint` is the path after /api/instances/{id}/{service}/, and the API
   * takes the selected row ids as `{ids: [...]}`. Only tabs whose rows carry a
   * numeric `id` can offer this — which is every *arr list, since the ids come
   * straight from the upstream API.
   */
  bulkDelete?: {
    endpoint: string;
    /** Button label, e.g. "Remove from queue". */
    label: string;
    /** Confirmation shown before the request; %d is the selected count. */
    confirm: string;
    /** Extra body fields the endpoint accepts alongside `ids`. */
    body?: Record<string, unknown>;
  };
  /**
   * Upstream commands this tab can trigger, shown as buttons in its header.
   *
   * Each `name` must be in the router's allowlist for the service, which
   * rejects anything else with a 400. These run in the background upstream,
   * so a success means accepted rather than finished.
   */
  commands?: { name: string; label: string }[];
  /** Offer a "test all" button that POSTs `{endpoint}/testall`. */
  testAll?: boolean;
};

const QUEUE_COLUMNS: ArrColumn[] = [
  { key: "title", header: "Title" },
  { key: "status", header: "Status" },
  { key: "size", header: "Size", kind: "bytes", align: "right" },
  { key: "sizeleft", header: "Remaining", kind: "bytes", align: "right" },
  { key: "estimatedCompletionTime", header: "ETA", kind: "date" },
];

const HISTORY_COLUMNS: ArrColumn[] = [
  { key: "sourceTitle", header: "Title" },
  { key: "eventType", header: "Event" },
  { key: "date", header: "Date", kind: "date" },
];

const WANTED_COLUMNS: ArrColumn[] = [
  { key: "title", header: "Title" },
  { key: "airDateUtc", header: "Air date", kind: "date" },
  { key: "monitored", header: "Monitored", kind: "boolean" },
];

const EVENT_COLUMNS: ArrColumn[] = [
  { key: "level", header: "Level" },
  { key: "logger", header: "Logger" },
  { key: "message", header: "Message" },
  { key: "time", header: "Time", kind: "date" },
];

const TASK_COLUMNS: ArrColumn[] = [
  { key: "name", header: "Task" },
  { key: "interval", header: "Interval", align: "right" },
  { key: "lastExecution", header: "Last run", kind: "date" },
  { key: "nextExecution", header: "Next run", kind: "date" },
];

const BACKUP_COLUMNS: ArrColumn[] = [
  { key: "name", header: "Name" },
  { key: "type", header: "Type" },
  { key: "size", header: "Size", kind: "bytes", align: "right" },
  { key: "time", header: "Created", kind: "date" },
];

const BLOCKLIST_COLUMNS: ArrColumn[] = [
  { key: "sourceTitle", header: "Title" },
  { key: "protocol", header: "Protocol" },
  { key: "date", header: "Date", kind: "date" },
];

const ARR_SHARED: Record<string, ArrTab> = {
  queue: {
    endpoint: "queue",
    title: "Queue",
    paged: false,
    columns: QUEUE_COLUMNS,
    empty: "The queue is empty.",
    commands: [{ name: "RefreshMonitoredDownloads", label: "Refresh downloads" }],
    bulkDelete: {
      endpoint: "queue/bulk",
      label: "Remove from queue",
      confirm: "Remove %d queue item(s)? They are also removed from the download client.",
      // Matches the upstream default: taking the item out of the queue
      // without taking it out of the client leaves the download running.
      body: { removeFromClient: true, blocklist: false },
    },
  },
  history: {
    endpoint: "history",
    title: "History",
    paged: true,
    columns: HISTORY_COLUMNS,
  },
  missing: {
    endpoint: "wanted/missing",
    title: "Missing",
    paged: true,
    columns: WANTED_COLUMNS,
    empty: "Nothing missing.",
    commands: [{ name: "MissingEpisodeSearch", label: "Search all missing" }],
  },
  cutoff: {
    endpoint: "wanted/cutoff",
    title: "Cutoff unmet",
    paged: true,
    columns: WANTED_COLUMNS,
    empty: "Nothing below cutoff.",
  },
  events: {
    endpoint: "events",
    title: "Events",
    paged: true,
    columns: EVENT_COLUMNS,
    commands: [{ name: "RssSync", label: "Check for new releases" }],
  },
  tasks: {
    endpoint: "system/tasks",
    title: "Tasks",
    paged: false,
    columns: TASK_COLUMNS,
    commands: [
      { name: "CheckHealth", label: "Check health" },
      { name: "Housekeeping", label: "Housekeeping" },
    ],
  },
  backups: {
    endpoint: "system/backups",
    title: "Backups",
    paged: false,
    columns: BACKUP_COLUMNS,
    empty: "No backups.",
    commands: [{ name: "Backup", label: "Back up now" }],
  },
  blocklist: {
    endpoint: "blocklist",
    title: "Blocklist",
    paged: true,
    columns: BLOCKLIST_COLUMNS,
    empty: "The blocklist is empty.",
    bulkDelete: {
      endpoint: "blocklist/bulk",
      label: "Remove from blocklist",
      confirm: "Remove %d blocklist entry(s)? They become eligible again.",
    },
  },
};

const ARR_TABS: Record<string, Record<string, ArrTab>> = {
  sonarr: ARR_SHARED,
  radarr: {
    ...ARR_SHARED,
    // Same tab, different upstream command name: the routers allowlist
    // MissingEpisodeSearch for Sonarr and MissingMoviesSearch for Radarr, and
    // sending the wrong one is a 400.
    missing: {
      ...ARR_SHARED.missing,
      commands: [{ name: "MissingMoviesSearch", label: "Search all missing" }],
    },
    collection: {
      endpoint: "collection",
      title: "Collections",
      paged: false,
      columns: [
        { key: "title", header: "Collection" },
        { key: "movieCount", header: "Movies", align: "right" },
        { key: "monitored", header: "Monitored", kind: "boolean" },
      ],
      empty: "No collections.",
    },
  },
};

/**
 * One cell's text, by the column's declared kind.
 *
 * Lives here rather than in the tab page because both the server-rendered
 * table and the selectable client one have to format a row identically — two
 * copies would drift the moment a new kind is added. `timeZone` is the app
 * zone, from `appTimeZone()` or `useTimeZone()` depending on the caller.
 */
export function renderArrCell(
  row: Record<string, unknown>,
  column: ArrColumn,
  timeZone: string,
): string {
  const raw = column.path ? readPath(row, column.path) : row[column.key];
  switch (column.kind) {
    case "bytes":
      return formatBytes(typeof raw === "number" ? raw : 0);
    case "date":
      return formatDateTime(raw, timeZone);
    case "boolean":
      return raw ? "Yes" : "No";
    default:
      if (raw === null || raw === undefined || raw === "") return "—";
      return String(raw);
  }
}

function isArrColumn(value: unknown): value is ArrColumn {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ArrColumn).key === "string" &&
    typeof (value as ArrColumn).header === "string"
  );
}

/**
 * A tab a service type declared in its `arr_tables` is data from the API,
 * not code: check the shape before trusting it, and skip a malformed one
 * rather than let `columns.map` take the whole route down.
 */
function declaredArrTab(
  value: unknown,
  serviceType: string,
  slug: string,
): ArrTab | undefined {
  if (value === undefined) return undefined;
  const tab = value as Partial<ArrTab> | null;
  const valid =
    typeof tab === "object" &&
    tab !== null &&
    typeof tab.endpoint === "string" &&
    tab.endpoint !== "" &&
    typeof tab.title === "string" &&
    typeof tab.paged === "boolean" &&
    Array.isArray(tab.columns) &&
    tab.columns.length > 0 &&
    tab.columns.every(isArrColumn);
  if (valid) return tab as ArrTab;
  console.warn(
    `Ignoring malformed arr_tables entry ${serviceType}/${slug} from /api/service-types`,
  );
  return undefined;
}

/**
 * The config for one tab: the private seam first, then the tables above,
 * then whatever the service type declared in its `arr_tables`.
 */
export function arrTabsFor(
  types: ServiceTypeMap,
  serviceType: string,
  slug: string,
): ArrTab | undefined {
  return (
    EXTRA_ARR_TABS[serviceType]?.[slug] ??
    ARR_TABS[serviceType]?.[slug] ??
    declaredArrTab(types[serviceType]?.arr_tables?.[slug], serviceType, slug)
  );
}
