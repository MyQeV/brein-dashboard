"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { DEFAULT_PAGE_SIZE, PAGE_SIZES } from "@/lib/params";
import {
  fetchPreferences,
  MODAL_LISTS_EXPANDED,
  type Preferences,
  setPreference,
} from "@/lib/preferences";

/**
 * Preference keys are `list_pagesize_<service>_<tab>`; the instance tab page
 * reads the same key for its default page size.
 */
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

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; prefs: Preferences };

export function ListPreferences() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchPreferences(controller.signal)
      .then((prefs) => {
        if (!controller.signal.aborted) setState({ status: "ok", prefs });
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message:
            caught instanceof Error ? caught.message : "Failed to load preferences",
        });
      });
    return () => controller.abort();
  }, []);

  async function save(key: string, value: number | boolean) {
    setSaving(key);
    setError(null);
    try {
      await setPreference(key, value);
      setState((current) =>
        current.status === "ok"
          ? { status: "ok", prefs: { ...current.prefs, [key]: value } }
          : current,
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not save the preference",
      );
    } finally {
      setSaving(null);
    }
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

  const modalListsExpanded = state.prefs[MODAL_LISTS_EXPANDED] === true;

  return (
    <>
      {error && (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      )}

      <Card title="Modal lists">
        <p className="mb-3 text-sm text-muted">
          How the day-by-day lists in the dashboard's dialogs start out.
        </p>
        <div className="flex items-center justify-between gap-4 py-2">
          <label htmlFor={MODAL_LISTS_EXPANDED} className="text-sm">
            Day groups
          </label>
          <Select
            size="sm"
            id={MODAL_LISTS_EXPANDED}
            value={modalListsExpanded ? "expanded" : "collapsed"}
            disabled={saving === MODAL_LISTS_EXPANDED}
            onChange={(event) =>
              save(MODAL_LISTS_EXPANDED, event.target.value === "expanded")
            }
          >
            <option value="collapsed">Collapsed</option>
            <option value="expanded">Expanded</option>
          </Select>
        </div>
      </Card>

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
                <Select
                  size="sm"
                  id={key}
                  value={value}
                  disabled={saving === key}
                  onChange={(event) => save(key, Number(event.target.value))}
                >
                  {PAGE_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </Select>
              </li>
            );
          })}
        </ul>
      </Card>
    </>
  );
}
