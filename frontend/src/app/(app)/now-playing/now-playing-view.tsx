"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { cn } from "@/lib/cn";
import { formatClock } from "@/lib/format";
import { type NowPlayingCard, toCard } from "@/lib/now-playing";
import type { NowPlayingSession } from "@/lib/types";
import { externalHref } from "@/lib/url";
import { useNowPlaying } from "@/lib/use-now-playing";

export function NowPlayingView({
  initialSessions,
}: {
  initialSessions: NowPlayingSession[];
}) {
  const { sessions, connection } = useNowPlaying(initialSessions);
  const [instanceFilter, setInstanceFilter] = useState<string>("all");

  const cards = useMemo(() => sessions.map(toCard), [sessions]);

  // The server reports a position every ten seconds; between those the clock
  // is advanced locally so it counts rather than jumping. `elapsedMs` starts
  // at zero on every payload, so the first render matches what the server
  // rendered and the position is only ever the server's plus the time since.
  const [elapsedMs, setElapsedMs] = useState(0);
  const receivedAt = useRef<number | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset the clock whenever a new payload arrives
  useEffect(() => {
    receivedAt.current = Date.now();
    setElapsedMs(0);
  }, [sessions]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (receivedAt.current !== null) setElapsedMs(Date.now() - receivedAt.current);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  /** The bar follows the ticking position, so it creeps rather than jumping. */
  function percentOf(card: NowPlayingCard): number {
    if (card.runtimeSeconds <= 0) return card.progressPct;
    return Math.min(100, Math.round((100 * positionOf(card)) / card.runtimeSeconds));
  }

  /** Where a stream is now: the last reported position, plus the time since. */
  function positionOf(card: NowPlayingCard): number {
    // A paused stream has not moved, and one already at the end must not run
    // past its own runtime while the next poll is pending.
    if (card.isPaused) return card.positionSeconds;
    const advanced = card.positionSeconds + elapsedMs / 1000;
    return card.runtimeSeconds > 0 ? Math.min(card.runtimeSeconds, advanced) : advanced;
  }

  const instances = useMemo(() => {
    const seen = new Map<string, string>();
    for (const card of cards) {
      if (card.instanceId)
        seen.set(card.instanceId, card.instanceLabel || card.instanceId);
    }
    return [...seen.entries()];
  }, [cards]);

  // A filter whose server has stopped streaming would hide every remaining
  // card while the select that could clear it is no longer rendered — the
  // page said "nothing is playing" with the sidebar badge still counting a
  // stream, and only a reload recovered. An id that has left the list falls
  // back to showing everything.
  const known = instances.some(([id]) => id === instanceFilter);
  const activeFilter = instanceFilter !== "all" && known ? instanceFilter : "all";
  const visible =
    activeFilter === "all"
      ? cards
      : cards.filter((card) => card.instanceId === activeFilter);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">
          Now playing{" "}
          <span className="text-sm font-normal text-muted">
            ({visible.length} {visible.length === 1 ? "stream" : "streams"})
          </span>
        </h1>

        <div className="flex items-center gap-3">
          {instances.length > 1 && (
            <label className="flex items-center gap-2 text-sm">
              Server
              <select
                value={activeFilter}
                onChange={(event) => setInstanceFilter(event.target.value)}
                className={`${CONTROL_HEIGHT.sm} rounded-md border border-border bg-bg px-2 text-sm`}
              >
                <option value="all">All</option>
                {instances.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <span className="text-xs text-muted" role="status">
            {connection === "live"
              ? "Live"
              : connection === "polling"
                ? "Updating every 10s"
                : "Connecting…"}
          </span>
        </div>
      </div>

      {visible.length === 0 ? (
        <Card>
          <p className="text-sm text-muted">Nothing is playing right now.</p>
        </Card>
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(20rem,1fr))] gap-4">
          {visible.map((card) => (
            <li
              key={`${card.instanceId}-${card.sessionId}`}
              className="flex overflow-hidden rounded-[10px] bg-card shadow-[0_2px_8px_rgba(0,0,0,0.2)]"
            >
              {card.posterUrl ? (
                // biome-ignore lint/performance/noImgElement: proxied through the API, not a local asset
                <img
                  src={card.posterUrl}
                  alt=""
                  aria-hidden="true"
                  className="w-25 shrink-0 self-stretch object-cover"
                />
              ) : (
                <span
                  className="w-25 shrink-0 self-stretch bg-border/40"
                  aria-hidden="true"
                />
              )}

              <div className="flex min-w-0 flex-1 flex-col gap-1 px-4 py-3">
                <div className="flex items-start justify-between gap-2">
                  <span
                    className="min-w-0 truncate text-base leading-snug font-semibold"
                    title={card.title}
                  >
                    {card.title}
                  </span>
                  {card.instanceLabel &&
                    (externalHref(card.serverUrl) ? (
                      // Opens what is playing, not just the server: the API
                      // already builds the deep link per backend and falls
                      // back to the base URL when it cannot.
                      // New tab: this leaves Brein for the server's own UI,
                      // and the page is a live view worth not navigating away
                      // from. noreferrer as well as noopener, since the target
                      // is a server on the user's own network.
                      <a
                        href={externalHref(card.serverUrl)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`Open “${card.title}” on ${card.instanceLabel}`}
                        className="max-w-40 shrink-0 truncate rounded border border-accent bg-surface px-2 py-0.5 text-xs font-semibold text-accent hover:bg-accent hover:text-bg"
                      >
                        {card.instanceLabel}
                      </a>
                    ) : (
                      <span className="max-w-40 shrink-0 truncate rounded border border-accent bg-surface px-2 py-0.5 text-xs font-semibold text-accent">
                        {card.instanceLabel}
                      </span>
                    ))}
                </div>

                {card.episodeLine && (
                  <span className="truncate text-sm text-muted" title={card.episodeLine}>
                    {card.episodeLine}
                  </span>
                )}

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  {externalHref(card.userUrl) ? (
                    <a
                      href={externalHref(card.userUrl)}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={`Open ${card.userName} on ${card.instanceLabel || "the server"}`}
                      className="rounded bg-surface px-2 py-0.5 text-xs font-semibold text-accent shadow-[0_1px_3px_rgba(0,0,0,0.2)] hover:bg-accent hover:text-bg"
                    >
                      {card.userName}
                    </a>
                  ) : (
                    <span className="rounded bg-surface px-2 py-0.5 text-xs font-semibold text-accent shadow-[0_1px_3px_rgba(0,0,0,0.2)]">
                      {card.userName}
                    </span>
                  )}
                  {card.playMethodLabel && (
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-xs",
                        card.playMethod === "transcode"
                          ? "border-warning/45 bg-warning/20 text-warning"
                          : "border-success/40 bg-success/15 text-success",
                      )}
                    >
                      {card.playMethodLabel}
                    </span>
                  )}
                </div>

                <div className="mt-auto flex flex-col gap-1 pt-2">
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 flex-1 rounded-[3px] bg-bg">
                      <span
                        className="block h-full rounded-[3px] bg-accent"
                        style={{ width: `${percentOf(card)}%` }}
                      />
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted">
                      {card.isPaused ? "Paused" : `${percentOf(card)}%`}
                    </span>
                  </div>
                  <span className="text-xs tabular-nums text-muted">
                    {formatClock(positionOf(card))}
                    {/* Live TV and anything else the server gives no runtime
                        for shows the position alone rather than "/ 0:00". */}
                    {card.runtimeSeconds > 0 && ` / ${formatClock(card.runtimeSeconds)}`}
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
