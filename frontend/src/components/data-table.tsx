import Link from "next/link";
import type { ReactNode } from "react";
import { CARD_TABLE } from "@/components/ui/table";
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
  cards = false,
}: {
  rows: Row[];
  columns: Column<Row>[];
  basePath?: string;
  headerQuery?: Record<string, string | number | undefined>;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  rowKey: (row: Row, index: number) => string;
  empty?: ReactNode;
  /**
   * Below `lg`, one card per row instead of a table that scrolls sideways:
   * the first column as the card's heading, the rest as labelled lines. For
   * a table with more columns than a phone has room for; a narrow one reads
   * better as it is.
   */
  cards?: boolean;
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

  function sortMark(column: string): ReactNode {
    if (sortBy !== column) return null;
    return <span aria-hidden="true">{sortDir === "desc" ? " ↓" : " ↑"}</span>;
  }

  return (
    <div className="overflow-x-auto">
      {/* The cards hide the header row, and with it the sort links; this
          strip is where sorting lives on a phone. */}
      {cards && basePath && (
        <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs lg:hidden">
          <span className="text-muted">Sort by</span>
          {columns.map((column) => {
            const href = headerHref(column.key);
            if (!href || !column.header) return null;
            return (
              <Link
                key={column.key}
                href={href}
                className={cn(
                  "hover:text-text",
                  sortBy === column.key ? "font-medium text-text" : "text-muted",
                )}
              >
                {column.header}
                {sortMark(column.key)}
              </Link>
            );
          })}
        </div>
      )}
      <table className={cn("w-full border-collapse text-sm", cards && CARD_TABLE.table)}>
        <thead className={cn(cards && CARD_TABLE.thead)}>
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
                      {sortMark(column.key)}
                    </Link>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className={cn(cards && CARD_TABLE.tbody)}>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row, index)}
              className={cards ? CARD_TABLE.row : "border-b border-border"}
            >
              {columns.map((column, columnIndex) => (
                <td
                  key={column.key}
                  data-label={cards ? column.header : undefined}
                  className={cn(
                    cards
                      ? columnIndex === 0
                        ? CARD_TABLE.lead
                        : column.header
                          ? CARD_TABLE.cell
                          : CARD_TABLE.bare
                      : "px-3 py-2",
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
