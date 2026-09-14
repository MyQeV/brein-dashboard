"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import type { MediaLibrary, MediaUser } from "@/lib/types";
import { UserEditModal } from "./user-modal";

type SortKey =
  | "name"
  | "state"
  | "role"
  | "libraries"
  | "max_simultaneous_streams"
  | "last_activity_date";

const COLUMNS: { key: SortKey; header: string; align?: "right" }[] = [
  { key: "name", header: "Name" },
  { key: "state", header: "State" },
  { key: "role", header: "Role" },
  { key: "libraries", header: "Libraries" },
  { key: "max_simultaneous_streams", header: "Streams", align: "right" },
  { key: "last_activity_date", header: "Last active" },
];

function formatDate(value: string | null, timeZone: string): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  // Explicit zone, not the viewer's. A client component is still rendered on
  // the server for the initial HTML, so a locale-default format produces one
  // string there and another in the browser — a hydration mismatch, and a
  // column whose meaning changes with who is looking at it.
  return parsed.toLocaleString("en-GB", { timeZone });
}

/**
 * The media server's users, sortable, with an edit dialog per row.
 *
 * A client component rather than the shared DataTable because both of the
 * things this table needs are interactive: sorting without a round trip, and
 * a row that opens a dialog. Sorting stays in memory — the API returns the
 * whole list in one response, so there is nothing to page or refetch.
 */
export function UsersTable({
  instanceId,
  users,
  libraries,
  canEdit,
  timeZone,
}: {
  instanceId: number;
  users: MediaUser[];
  libraries: MediaLibrary[];
  /** Emby and Jellyfin own their accounts; Plex's live on plex.tv. */
  canEdit: boolean;
  /** The app's zone, resolved on the server so both renders agree. */
  timeZone: string;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "name",
    dir: "asc",
  });
  const [editing, setEditing] = useState<MediaUser | null>(null);

  const libraryName = useMemo(
    () => new Map(libraries.map((library) => [library.id, library.name])),
    [libraries],
  );

  const librariesLabel = useMemo(
    () => (row: MediaUser) =>
      row.enable_all_folders
        ? "All"
        : row.enabled_folder_ids.length === 0
          ? "None"
          : row.enabled_folder_ids
              .map((folderId) => libraryName.get(folderId) ?? folderId)
              .join(", "),
    [libraryName],
  );

  const sorted = useMemo(() => {
    // Compared as the column reads, not as it is stored: sorting State by the
    // raw boolean would order by false/true rather than by the words shown.
    const value = (row: MediaUser): string | number => {
      switch (sort.key) {
        case "state":
          return row.is_disabled ? "Disabled" : "Enabled";
        case "role":
          return row.is_administrator ? "Administrator" : "User";
        case "libraries":
          return librariesLabel(row);
        case "max_simultaneous_streams":
          return row.max_simultaneous_streams ?? 0;
        case "last_activity_date":
          // Never-active sorts as the oldest rather than as an empty string,
          // so ascending puts it first and descending last, as expected.
          return row.last_activity_date ? Date.parse(row.last_activity_date) : 0;
        default:
          return row.name.toLowerCase();
      }
    };
    return [...users].sort((a, b) => {
      const left = value(a);
      const right = value(b);
      const order =
        typeof left === "number" && typeof right === "number"
          ? left - right
          : String(left).localeCompare(String(right));
      return sort.dir === "asc" ? order : -order;
    });
  }, [users, sort, librariesLabel]);

  function toggleSort(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }

  if (users.length === 0) {
    return <p className="py-6 text-sm text-muted">This server has no users.</p>;
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              {COLUMNS.map((column) => {
                const active = sort.key === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={
                      active ? (sort.dir === "desc" ? "descending" : "ascending") : "none"
                    }
                    className={cn(
                      "px-3 py-2 font-medium text-muted",
                      column.align === "right" && "text-right",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className="cursor-pointer hover:text-text"
                    >
                      {column.header}
                      {active && (
                        <span aria-hidden="true">
                          {sort.dir === "desc" ? " ↓" : " ↑"}
                        </span>
                      )}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.id}
                onClick={() => {
                  if (!canEdit) return;
                  // Dragging across a name to copy it should not also open
                  // the dialog, as on the *arr tables.
                  if (window.getSelection()?.toString()) return;
                  setEditing(row);
                }}
                className={cn(
                  "border-b border-border last:border-0",
                  canEdit && "cursor-pointer hover:bg-border/30",
                )}
              >
                <td className="px-3 py-2">
                  {canEdit ? (
                    // The row carries the click; this is the keyboard path to
                    // the same dialog.
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setEditing(row);
                      }}
                      className="cursor-pointer text-left hover:text-accent"
                    >
                      {row.name}
                    </button>
                  ) : (
                    row.name
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className={row.is_disabled ? "text-muted" : "text-success"}>
                    {row.is_disabled ? "Disabled" : "Enabled"}
                  </span>
                </td>
                <td className="px-3 py-2">
                  {row.is_administrator ? "Administrator" : "User"}
                </td>
                <td className="px-3 py-2">{librariesLabel(row)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {row.max_simultaneous_streams > 0
                    ? String(row.max_simultaneous_streams)
                    : "Unlimited"}
                </td>
                <td className="px-3 py-2">
                  {formatDate(row.last_activity_date, timeZone)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <UserEditModal
          instanceId={instanceId}
          user={editing}
          libraries={libraries}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
