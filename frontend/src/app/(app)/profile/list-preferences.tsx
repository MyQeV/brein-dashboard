"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { Spinner } from "@/components/ui/spinner";
import { clientFetch } from "@/lib/client-fetch";
import { PAGE_SIZES } from "@/lib/params";

/** Preference keys are `list_pagesize_<service>_<list>`. */
const PAGE_SIZE_LISTS: { key: string; label: string }[] = [
  { key: "list_pagesize_sonarr_queue", label: "Sonarr — Queue" },
  { key: "list_pagesize_sonarr_history", label: "Sonarr — History" },
  { key: "list_pagesize_sonarr_blocklist", label: "Sonarr — Blocklist" },
  { key: "list_pagesize_sonarr_missing", label: "Sonarr — Missing" },
  { key: "list_pagesize_sonarr_cutoff", label: "Sonarr — Cutoff" },
  { key: "list_pagesize_sonarr_events", label: "Sonarr — Events" },
  { key: "list_pagesize_radarr_queue", label: "Radarr — Queue" },
  { key: "list_pagesize_radarr_history", label: "Radarr — History" },
  { key: "list_pagesize_radarr_blocklist", label: "Radarr — Blocklist" },
  { key: "list_pagesize_radarr_missing", label: "Radarr — Missing" },
  { key: "list_pagesize_radarr_cutoff", label: "Radarr — Cutoff" },
  { key: "list_pagesize_radarr_events", label: "Radarr — Events" },
];

const COLUMN_PREFIX = "list_columns_";
const DEFAULT_PAGE_SIZE = 10;

type Prefs = Record<string, unknown>;

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; prefs: Prefs };

export function ListPreferences() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const prefs = await clientFetch<Prefs>("/api/user/preferences", { signal });
      if (!signal?.aborted) setState({ status: "ok", prefs });
    } catch (error) {
      if (signal?.aborted) return;
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Failed to load preferences",
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function setPageSize(key: string, value: number) {
    setSaving(key);
    try {
      await clientFetch(`/api/user/preferences/${encodeURIComponent(key)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ value }),
      });
      setState((current) =>
        current.status === "ok"
          ? { status: "ok", prefs: { ...current.prefs, [key]: value } }
          : current,
      );
    } finally {
      setSaving(null);
    }
  }

  async function resetColumn(key: string) {
    await clientFetch(`/api/user/preferences/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
    await load();
  }

  async function resetAllColumns() {
    await clientFetch(
      `/api/user/preferences?prefix=${encodeURIComponent(COLUMN_PREFIX)}`,
      { method: "DELETE" },
    );
    await load();
  }

  if (state.status === "loading") {
    return (
      <Card title="List preferences">
        <Spinner label="Loading preferences…" />
      </Card>
    );
  }

  if (state.status === "error") {
    return (
      <Card title="List preferences">
        <p role="alert" className="text-sm text-error">
          {state.message}
        </p>
      </Card>
    );
  }

  const savedColumnKeys = Object.keys(state.prefs)
    .filter((key) => key.startsWith(COLUMN_PREFIX))
    .sort();

  return (
    <>
      <Card title="List page sizes">
        <p className="mb-3 text-sm text-muted">Rows shown per page for each list.</p>
        <ul className="flex flex-col divide-y divide-border">
          {PAGE_SIZE_LISTS.map(({ key, label }) => {
            const raw = state.prefs[key];
            const value = typeof raw === "number" ? raw : DEFAULT_PAGE_SIZE;
            return (
              <li key={key} className="flex items-center justify-between gap-4 py-2">
                <label htmlFor={key} className="text-sm">
                  {label}
                </label>
                <select
                  id={key}
                  value={value}
                  disabled={saving === key}
                  onChange={(event) => setPageSize(key, Number(event.target.value))}
                  className={`${CONTROL_HEIGHT.sm} rounded-md border border-border bg-bg px-2 text-sm`}
                >
                  {PAGE_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card
        title="Saved column layouts"
        actions={
          savedColumnKeys.length > 0 && (
            <Button size="sm" variant="danger" onClick={resetAllColumns}>
              Reset all
            </Button>
          )
        }
      >
        {savedColumnKeys.length === 0 ? (
          <p className="text-sm text-muted">
            No saved layouts. Lists are using their default columns.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {savedColumnKeys.map((key) => (
              <li key={key} className="flex items-center justify-between gap-4 py-2">
                <span className="truncate text-sm">
                  {key.slice(COLUMN_PREFIX.length).replace(/_/g, " ")}
                </span>
                <Button size="sm" variant="ghost" onClick={() => resetColumn(key)}>
                  Reset
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
