"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { CARD_TABLE } from "@/components/ui/table";
import type { ActionResult } from "@/lib/actions";
import { type ArrColumn, type ArrTab, renderArrCell } from "@/lib/arr-tabs";
import { cn } from "@/lib/cn";
import { useTimeZone } from "@/lib/timezone-context";
import { bulkDeleteRows } from "./actions";

/**
 * The *arr list table, with row selection and a bulk delete.
 *
 * The API has taken `{ids: [...]}` on `queue/bulk` and `blocklist/bulk` since
 * those routes were written, and nothing ever called them — the tables listed
 * the rows and offered no way to act on them, so removing a stuck download
 * meant opening Radarr itself. Only tabs that declare `bulkDelete` render
 * this; the rest keep the plain server-rendered table.
 */
export function SelectableArrTable({
  instanceId,
  service,
  tab,
  rows,
  columns,
  bulk,
  empty,
}: {
  instanceId: number;
  service: string;
  tab: string;
  rows: Record<string, unknown>[];
  columns: ArrColumn[];
  bulk: NonNullable<ArrTab["bulkDelete"]>;
  empty: string;
}) {
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();
  const timeZone = useTimeZone();

  // Only rows the API can act on: the bulk endpoints key on the upstream id,
  // and a row without one cannot be part of the request.
  const selectable = rows
    .map((row) => (typeof row.id === "number" ? row.id : null))
    .filter((id): id is number => id !== null);

  const allSelected = selectable.length > 0 && selected.size === selectable.length;

  function toggle(id: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(selectable));
  }

  function remove() {
    const ids = [...selected];
    if (ids.length === 0) return;
    if (!window.confirm(bulk.confirm.replace("%d", String(ids.length)))) return;
    setResult(null);
    startTransition(async () => {
      const outcome = await bulkDeleteRows(
        instanceId,
        service,
        bulk.endpoint,
        ids,
        bulk.body ?? {},
        tab,
      );
      setResult(outcome);
      // Keep a failed selection so the action can be retried; a successful one
      // refers to rows that no longer exist.
      if (outcome.ok) setSelected(new Set());
    });
  }

  if (rows.length === 0) {
    return <p className="py-6 text-sm text-muted">{empty}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="danger"
          size="sm"
          disabled={selected.size === 0 || pending}
          onClick={remove}
        >
          {pending
            ? "Removing…"
            : `${bulk.label}${selected.size ? ` (${selected.size})` : ""}`}
        </Button>
        {selected.size > 0 && (
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
        )}
        {result && !result.ok && (
          <span role="alert" className="text-sm text-error">
            {result.error}
          </span>
        )}
        {result?.ok && (
          <span role="status" className="text-sm text-success">
            Done.
          </span>
        )}
      </div>

      {/* On a phone the row is a card: the checkbox and the title share its
          first line, the other columns are labelled under them. */}
      <table className={CARD_TABLE.table}>
        <thead className={CARD_TABLE.thead}>
          <tr className="border-b border-border text-left">
            <th scope="col" className="w-8 py-2 pl-3 pr-1">
              <input
                type="checkbox"
                aria-label={allSelected ? "Deselect all rows" : "Select all rows"}
                checked={allSelected}
                onChange={toggleAll}
                disabled={selectable.length === 0}
              />
            </th>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "px-3 py-2 font-medium text-muted",
                  column.align === "right" && "text-right",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={CARD_TABLE.tbody}>
          {rows.map((row, index) => {
            const id = typeof row.id === "number" ? row.id : null;
            const checked = id !== null && selected.has(id);
            return (
              <tr
                key={String(row.id ?? index)}
                // The whole row toggles: a 6px checkbox is a small target in
                // a table this wide. The checkbox inside stays the keyboard
                // path and carries the state, as the drill-down rows do.
                onClick={() => {
                  if (id === null) return;
                  // Dragging across a title to copy it should not also
                  // select the row.
                  if (window.getSelection()?.toString()) return;
                  toggle(id);
                }}
                // Not CARD_TABLE.row: that stacks the cells, and here the
                // checkbox and the title share the first line.
                className={cn(
                  "border-b border-border last:border-0",
                  "max-lg:flex max-lg:flex-wrap max-lg:gap-x-3 max-lg:gap-y-1 max-lg:py-3",
                  id !== null && "cursor-pointer hover:bg-border/30",
                  checked && "bg-accent/10",
                )}
              >
                {/* biome-ignore lint/a11y/useKeyWithClickEvents: the handler only keeps the click from reaching the row; the checkbox inside is the keyboard path */}
                <td
                  className="py-2 pl-3 pr-1 max-lg:p-0"
                  // The row handles the click too; without this the
                  // checkbox would toggle and then untoggle.
                  onClick={(event) => event.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    // Every *arr list row carries an upstream id; the guard
                    // is for the one that somehow does not, which cannot be
                    // part of the request either way.
                    disabled={id === null}
                    checked={checked}
                    onChange={() => id !== null && toggle(id)}
                    aria-label={`Select ${renderArrCell(row, columns[0], timeZone)}`}
                    className="cursor-pointer"
                  />
                </td>
                {columns.map((column, index) => (
                  <td
                    key={column.key}
                    data-label={column.header}
                    className={cn(
                      index === 0
                        ? cn(CARD_TABLE.lead, "max-lg:min-w-0 max-lg:flex-1")
                        : cn(CARD_TABLE.cell, "max-lg:w-full"),
                      column.align === "right" && "text-right tabular-nums",
                    )}
                  >
                    {renderArrCell(row, column, timeZone)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
