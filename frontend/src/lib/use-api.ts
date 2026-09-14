"use client";

import { useEffect, useState } from "react";
import { clientFetch } from "./client-fetch";

/**
 * A client-side GET, as a hook.
 *
 * Every card that loads its own data had written the same effect: set
 * loading, fetch with an AbortController, ignore the result if the signal
 * fired, map the rejection to a message, abort on cleanup. The abort is the
 * part worth centralising — without it a slow response for the previous
 * filter lands after the new one and the card shows the wrong range, which is
 * a bug that only appears on a slow connection.
 */

export type Fetched<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; data: T };

/**
 * Fetch `path`, re-fetching whenever it changes.
 *
 * `path` may be null to hold off (a card whose input is not chosen yet), in
 * which case the state stays "loading" and no request is made.
 */
export function useApi<T>(path: string | null): Fetched<T> {
  const [state, setState] = useState<Fetched<T>>({ status: "loading" });

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    setState({ status: "loading" });

    clientFetch<T>(path, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setState({ status: "ok", data });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Failed to load",
        });
      });

    return () => controller.abort();
  }, [path]);

  return state;
}
