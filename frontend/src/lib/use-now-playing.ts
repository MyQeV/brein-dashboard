"use client";

import { useEffect, useState } from "react";
import { clientFetch } from "@/lib/client-fetch";
import type { NowPlayingSession } from "@/lib/types";

export type NowPlayingConnection = "connecting" | "live" | "polling";

const POLL_INTERVAL_MS = 10_000;
// Retried with backoff: a single drop (a proxy restart, a laptop lid) is not
// a reason to poll for the rest of the page's life.
const RECONNECT_BASE_MS = 5_000;
const RECONNECT_MAX_MS = 60_000;

/**
 * Live playback sessions: the WebSocket broadcast, falling back to polling.
 *
 * Mounted once, by the shell's provider, so the Now playing page and the
 * sidebar counter share one socket and cannot disagree about how many
 * streams are running. `loaded` is false until the first payload arrives;
 * until then `sessions` is the empty default, and a page that rendered its
 * own list on the server keeps showing that instead.
 */
export function useNowPlaying(): {
  sessions: NowPlayingSession[];
  connection: NowPlayingConnection;
  loaded: boolean;
} {
  const [sessions, setSessions] = useState<NowPlayingSession[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [connection, setConnection] = useState<NowPlayingConnection>("connecting");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let closed = false;

    function apply(items: NowPlayingSession[]) {
      if (closed) return;
      setSessions(items);
      setLoaded(true);
    }

    // Through clientFetch, not a bare fetch: once the access cookie expires
    // a bare poll gets 401 for the rest of the page's life, and hiding that
    // behind `response.ok` meant the list quietly froze.
    async function load() {
      try {
        const data = await clientFetch<{ items: NowPlayingSession[] }>(
          "/api/now-playing",
        );
        apply(data.items);
      } catch {
        // Transient or already signed out; the next poll or frame will tell.
      }
    }

    function startPolling() {
      if (pollTimer || closed) return;
      setConnection("polling");
      pollTimer = setInterval(() => void load(), POLL_INTERVAL_MS);
    }

    function stopPolling() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    }

    function scheduleReconnect() {
      if (closed || reconnectTimer) return;
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attempts);
      attempts += 1;
      reconnectTimer = setTimeout(async () => {
        reconnectTimer = null;
        // The upgrade carries whatever access cookie the browser has, and a
        // socket the server closed for an expired one would only be refused
        // again. A poll first: it goes through clientFetch, which refreshes
        // the session, so the next upgrade carries a live cookie.
        await load();
        connect();
      }, delay);
    }

    function connect() {
      if (closed) return;
      try {
        const scheme = window.location.protocol === "https:" ? "wss" : "ws";
        socket = new WebSocket(`${scheme}://${window.location.host}/ws/now-playing`);
      } catch {
        startPolling();
        scheduleReconnect();
        return;
      }

      socket.onopen = () => {
        if (closed) return;
        attempts = 0;
        stopPolling();
        setConnection("live");
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { items?: NowPlayingSession[] };
          if (Array.isArray(payload.items)) apply(payload.items);
        } catch {
          // A frame we cannot parse is not worth tearing the socket down for.
        }
      };
      // Falling back to polling rather than showing an error: the page still
      // works, just less promptly. An error event is always followed by
      // close, so this is the one place the fallback happens.
      socket.onclose = () => {
        socket = null;
        startPolling();
        scheduleReconnect();
      };
    }

    // Without an initial payload the first frame is whatever the socket sends
    // next, which can be a minute away — so seed from the API right now.
    void load();
    connect();

    return () => {
      closed = true;
      stopPolling();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  return { sessions, connection, loaded };
}
