"use client";

import { useEffect, useState } from "react";
import type { NowPlayingSession } from "@/lib/types";

export type NowPlayingConnection = "connecting" | "live" | "polling";

const POLL_INTERVAL_MS = 10_000;

/**
 * Live playback sessions: the WebSocket broadcast, falling back to polling.
 *
 * Shared by the Now playing page and the sidebar counter, so the two cannot
 * disagree about how many streams are running.
 */
export function useNowPlaying(initialSessions: NowPlayingSession[] = []): {
  sessions: NowPlayingSession[];
  connection: NowPlayingConnection;
} {
  const [sessions, setSessions] = useState(initialSessions);
  const [connection, setConnection] = useState<NowPlayingConnection>("connecting");

  // biome-ignore lint/correctness/useExhaustiveDependencies: seeded once; later renders must not tear the socket down
  useEffect(() => {
    let socket: WebSocket | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let closed = false;

    function load() {
      fetch("/api/now-playing", { credentials: "include" })
        .then((response) => (response.ok ? response.json() : null))
        .then((data: { items: NowPlayingSession[] } | null) => {
          if (data && !closed) setSessions(data.items);
        })
        .catch(() => undefined);
    }

    function startPolling() {
      if (pollTimer || closed) return;
      setConnection("polling");
      pollTimer = setInterval(load, POLL_INTERVAL_MS);
    }

    // Without an initial payload the first frame is whatever the socket sends
    // next, which can be a minute away — so seed from the API right now.
    if (initialSessions.length === 0) load();

    try {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${window.location.host}/ws/now-playing`);

      socket.onopen = () => {
        if (!closed) setConnection("live");
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { items?: NowPlayingSession[] };
          if (Array.isArray(payload.items) && !closed) setSessions(payload.items);
        } catch {
          // A frame we cannot parse is not worth tearing the socket down for.
        }
      };
      // Falling back to polling rather than showing an error: the page still
      // works, just less promptly.
      socket.onerror = startPolling;
      socket.onclose = startPolling;
    } catch {
      startPolling();
    }

    return () => {
      closed = true;
      if (pollTimer) clearInterval(pollTimer);
      socket?.close();
    };
  }, []);

  return { sessions, connection };
}
