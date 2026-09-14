import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Column<Row> = {
  key: string;
  header: string;
  align?: "left" | "right";
  render?: (row: Row) => ReactNode;
};

/**
 * Server-rendered table with sortable headers.
 *
 * `headerQuery` must NOT contain sort, direction or page — those are what a
 * header link sets. Passing them through would make every header carry the
 * previous sort and page, so clicking one would not change anything.
 */
export function DataTable<Row extends Record<string, unknown>>({
  rows,
  columns,
  basePath,
  headerQuery,
  sortBy,
  sortDir,
  rowKey,
  empty = "Nothing to show.",
}: {
  rows: Row[];
  columns: Column<Row>[];
  basePath?: string;
  headerQuery?: Record<string, string | number | undefined>;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  rowKey: (row: Row, index: number) => string;
  empty?: ReactNode;
}) {
  if (rows.length === 0) {
    return <p className="py-6 text-sm text-muted">{empty}</p>;
  }

  function headerHref(column: string): string | undefined {
    if (!basePath) return undefined;
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(headerQuery ?? {})) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    params.set("sort_by", column);
    params.set("sort_dir", sortBy === column && sortDir === "asc" ? "desc" : "asc");
    return `${basePath}?${params.toString()}`;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            {columns.map((column) => {
              const active = sortBy === column.key;
              const href = headerHref(column.key);
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={
                    active ? (sortDir === "desc" ? "descending" : "ascending") : "none"
                  }
                  className={cn(
                    "px-3 py-2 font-medium text-muted",
                    column.align === "right" && "text-right",
                  )}
                >
                  {href ? (
                    // A link, not a click handler on the <th>: sorting must be
                    // keyboard reachable and shareable as a URL.
                    <Link href={href} className="hover:text-text">
                      {column.header}
                      {active && (
                        <span aria-hidden="true">{sortDir === "desc" ? " ↓" : " ↑"}</span>
                      )}
                    </Link>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)} className="border-b border-border">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    "px-3 py-2",
                    column.align === "right" && "text-right tabular-nums",
                  )}
                >
                  {column.render ? column.render(row) : String(row[column.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
