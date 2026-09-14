"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a media query matches, kept current as the viewport changes.
 *
 * The server snapshot is `false`, so a component that renders one layout or
 * the other picks the wide one on the server. Use it only where that cannot
 * flash — inside a dialog, which mounts on the client — or where the two
 * layouts share their first paint.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
