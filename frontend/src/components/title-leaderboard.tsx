"use client";

import { useState } from "react";
import { DrillModal, type DrillTarget } from "@/components/drill-modal";
import { Card } from "@/components/ui/card";
import { formatDuration } from "@/lib/format";
import { type ApiRow, rowNumber, rowText } from "@/lib/rows";

type Row = { label: string; seconds: number };

/**
 * Watch time by title, ranked, with a drill-down per row.
 *
 * The Movies and Series tabs are the same table over a different metric — the
 * only differences are the heading, which API list is read, and which drill
 * the click opens. Keeping one component means a fix to the ranking or the
 * keyboard path lands on both tabs rather than on whichever was edited.
 */
export function TitleLeaderboard({
  rows: apiRows,
  title,
  emptyLabel,
  drillType,
  query,
  timeZone,
}: {
  rows: ApiRow[];
  /** Card heading; the row count is appended when there are rows. */
  title: string;
  emptyLabel: string;
  drillType: DrillTarget["drillType"];
  query: string;
  timeZone: string;
}) {
  const [drill, setDrill] = useState<DrillTarget | null>(null);

  // Re-sorted here: the table's order is its own business, not the API's.
  const rows: Row[] = apiRows
    .map((row) => ({ label: rowText(row), seconds: rowNumber(row) }))
    .filter((row) => row.label !== "")
    .sort((a, b) => b.seconds - a.seconds);

  const total = rows.reduce((sum, row) => sum + row.seconds, 0);

  function open(row: Row) {
    // The drill matches on the title, so the label is both id and heading.
    setDrill({ drillType, id: row.label, title: row.label });
  }

  return (
    <>
      <Card title={rows.length > 0 ? `${title} — ${rows.length}` : title}>
        {rows.length === 0 ? (
          <p className="py-6 text-sm text-muted">{emptyLabel}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted">
                  <th scope="col" className="w-8 py-2 pr-2 text-right font-normal">
                    #
                  </th>
                  <th scope="col" className="py-2 font-normal">
                    Title
                  </th>
                  <th scope="col" className="py-2 text-right font-normal">
                    Watch time
                  </th>
                  <th scope="col" className="w-16 py-2 text-right font-normal">
                    Share
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr
                    key={row.label}
                    onClick={() => open(row)}
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-border/30"
                  >
                    <td className="py-1.5 pr-2 text-right tabular-nums text-muted">
                      {index + 1}
                    </td>
                    <td className="py-1.5">
                      {/* The row carries the click; this is the keyboard path
                          to the same drill-down. */}
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          open(row);
                        }}
                        className="w-full cursor-pointer text-left hover:text-accent"
                      >
                        {row.label}
                      </button>
                    </td>
                    <td className="py-1.5 text-right tabular-nums whitespace-nowrap">
                      {formatDuration(row.seconds)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums text-muted">
                      {total > 0 ? `${Math.round((row.seconds / total) * 100)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {drill && (
        <DrillModal
          target={drill}
          query={query}
          timeZone={timeZone}
          onClose={() => setDrill(null)}
        />
      )}
    </>
  );
}
