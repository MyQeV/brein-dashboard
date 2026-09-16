"use client";

import { useEffect, useState } from "react";
import { clientFetch } from "./client-fetch";

/**
 * The user's preferences: /api/user/preferences, in one place.
 *
 * Three screens had each written their own fetch of the whole map and their
 * own PUT of one key. Nothing is cached here on purpose: the readers are
 * modals and settings cards, which already wait on a request of their own
 * before they show anything, and a cache would outlive a sign-out in the
 * same tab.
 */

/** Preference keys the profile page writes and other screens read. */
export const MODAL_LISTS_EXPANDED = "modal_lists_expanded";

export type Preferences = Record<string, unknown>;

const BASE = "/api/user/preferences";

/** Every preference of the signed-in user, as the API stores them. */
export function fetchPreferences(signal?: AbortSignal): Promise<Preferences> {
  return clientFetch<Preferences>(BASE, { signal });
}

export function setPreference(key: string, value: unknown): Promise<void> {
  return clientFetch<void>(`${BASE}/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ value }),
  });
}

export function deletePreference(key: string): Promise<void> {
  return clientFetch<void>(`${BASE}/${encodeURIComponent(key)}`, { method: "DELETE" });
}

/**
 * One boolean from the user's preferences, `fallback` until it has loaded or
 * when it was never set.
 */
export function useBooleanPreference(key: string, fallback = false): boolean {
  const [value, setValue] = useState(fallback);

  useEffect(() => {
    const controller = new AbortController();
    fetchPreferences(controller.signal)
      .then((prefs) => {
        const saved = prefs[key];
        if (!controller.signal.aborted && typeof saved === "boolean") setValue(saved);
      })
      .catch(() => {
        // Best-effort: the fallback is a perfectly good answer.
      });
    return () => controller.abort();
  }, [key]);

  return value;
}
