"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { buildQuery } from "@/lib/params";
import { useApi } from "@/lib/use-api";

/** One row of `items` from GET /api/dashboard/library-unwatched. */
type UnwatchedItem = {
  instance_id: number;
  instance_label: string;
  item_id: string;
  title: string;
  season_number: number | null;
  episode_number: number | null;
  updated_at: string;
};

/** The API caps `limit` at 1000; the list says which slice it is showing. */
const ITEM_LIMIT = 200;

const TYPES = [
  { value: "Movie", label: "Movies" },
  { value: "Episode", label: "Episodes" },
] as const;

type ItemType = (typeof TYPES)[number]["value"];

/**
 * "S01E02" only when both numbers are there — an episode row with a missing
 * index would otherwise render as "SundefinedE2".
 */
function episodeCode(item: UnwatchedItem): string | null {
  const { season_number: season, episode_number: episode } = item;
  if (typeof season !== "number" || typeof episode !== "number") return null;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `S${pad(season)}E${pad(episode)}`;
}

/**
 * The titles behind the "never played" tile. `items` is only returned when the
 * API is given an `item_type`, so this list is always scoped to one of them.
 */
export function UnwatchedItems({ instanceIds }: { instanceIds?: string }) {
  const [itemType, setItemType] = useState<ItemType>("Movie");

  // The page already rendered the summary; recomputing it here made every
  // toggle pay for a second anti-join over the whole library.
  const query = buildQuery({
    item_type: itemType,
    instance_ids: instanceIds,
    limit: ITEM_LIMIT,
    include_summary: "false",
  });
  const state = useApi<{ items: UnwatchedItem[] }>(
    `/api/dashboard/library-unwatched${query}`,
  );
  const items = state.status === "ok" ? (state.data.items ?? []) : [];

  const typeControl = (
    <fieldset className="flex gap-1 border-0 p-0">
      <legend className="sr-only">Item type</legend>
      {TYPES.map((option) => (
        <Button
          key={option.value}
          size="sm"
          variant={itemType === option.value ? "primary" : "ghost"}
          aria-pressed={itemType === option.value}
          onClick={() => setItemType(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </fieldset>
  );

  return (
    <Card
      title={
        <>
          Never played
          <span className="ml-2 font-normal text-muted">
            first {ITEM_LIMIT}, by title
          </span>
        </>
      }
      actions={typeControl}
    >
      {state.status === "loading" && <Spinner label="Loading titles…" />}

      {state.status === "error" && (
        <p className="text-sm text-error" role="alert">
          {state.message}
        </p>
      )}

      {state.status === "ok" && items.length === 0 && (
        <p className="py-6 text-sm text-muted">
          {itemType === "Movie"
            ? "Every movie in the library has been played."
            : "Every episode in the library has been played."}
        </p>
      )}

      {state.status === "ok" && items.length > 0 && (
        <ul className="flex flex-col">
          {items.map((item) => {
            const code = episodeCode(item);
            return (
              <li
                key={`${item.instance_id}:${item.item_id}`}
                className="flex items-baseline justify-between gap-3 border-b border-border py-2 text-sm last:border-b-0"
              >
                <span>
                  {item.title}
                  {code && <span className="ml-1 tabular-nums text-muted">({code})</span>}
                </span>
                <span className="shrink-0 text-xs text-muted">{item.instance_label}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
