"use client";

import { useEffect, useState } from "react";
import { clientFetch } from "./client-fetch";

/** Preference keys the profile page writes and other screens read. */
export const MODAL_LISTS_EXPANDED = "modal_lists_expanded";

/**
 * One boolean from the user's preferences, `fallback` until it has loaded or
 * when it was never set.
 *
 * Fetched on every mount rather than cached: the readers are modals, which
 * already wait on a request of their own before they show anything, and a
 * cache would outlive a sign-out in the same tab.
 */
export function useBooleanPreference(key: string, fallback = false): boolean {
  const [value, setValue] = useState(fallback);

  useEffect(() => {
    const controller = new AbortController();
    clientFetch<Record<string, unknown>>("/api/user/preferences", {
      signal: controller.signal,
    })
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
