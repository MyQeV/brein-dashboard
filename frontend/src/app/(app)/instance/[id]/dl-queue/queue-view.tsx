"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { CARD_TABLE } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import type { DownloadQueue } from "@/lib/types";
import {
  type ActionResult,
  deleteItem,
  pauseItem,
  pauseQueue,
  pauseQueueTimed,
  resumeItem,
  resumeQueue,
  setSpeedLimit,
} from "./actions";

const REFRESH_MS = 5000;

function formatEta(eta: string | number | null): string {
  if (eta === null || eta === "" || eta === 0) return "—";
  if (typeof eta === "number") {
    const hours = Math.floor(eta / 3600);
    const minutes = Math.round((eta % 3600) / 60);
    return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
  }
  return eta;
}

export function QueueView({
  instanceId,
  queue,
}: {
  instanceId: number;
  queue: DownloadQueue;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(
    String(queue.speed_limit_pct ?? queue.speed_limit_bytes ?? 0),
  );
  const [pauseMinutes, setPauseMinutes] = useState("30");
  const [pending, startTransition] = useTransition();

  // A download queue is live data; re-fetch on a timer rather than making the
  // user reload to see progress.
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [router]);

  function act(action: () => Promise<ActionResult>) {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (!result.ok) setError(result.error);
      else router.refresh();
    });
  }

  const isSab = queue.service_type === "sabnzbd";
  const perItemPause = queue.capabilities.per_item_pause;
  const queueLevelPause = queue.capabilities.queue_level_pause;

  return (
    <div className="flex flex-col gap-4">
      <Card title="Controls">
        <div className="flex flex-wrap items-end gap-3">
          {queueLevelPause &&
            (queue.paused ? (
              <Button
                disabled={pending}
                onClick={() => act(() => resumeQueue(instanceId))}
              >
                Resume queue
              </Button>
            ) : (
              <Button
                variant="secondary"
                disabled={pending}
                onClick={() => act(() => pauseQueue(instanceId))}
              >
                Pause queue
              </Button>
            ))}

          {/* SABnzbd runs the timer itself, so the queue comes back on its
              own even if Brein restarts meanwhile. */}
          {isSab && !queue.paused && (
            <label className="flex flex-col gap-1 text-sm">
              Pause for (minutes)
              <span className="flex gap-2">
                <input
                  value={pauseMinutes}
                  inputMode="numeric"
                  onChange={(event) => setPauseMinutes(event.target.value)}
                  className={`${CONTROL_HEIGHT.sm} w-24 rounded-md border border-border bg-bg px-2 text-sm`}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={pending}
                  onClick={() => {
                    const parsed = Number.parseInt(pauseMinutes, 10);
                    if (!Number.isFinite(parsed) || parsed < 1 || parsed > 24 * 60) {
                      setError("Pause must be between 1 minute and 24 hours.");
                      return;
                    }
                    act(() => pauseQueueTimed(instanceId, parsed));
                  }}
                >
                  Pause
                </Button>
              </span>
            </label>
          )}

          <label className="flex flex-col gap-1 text-sm">
            {isSab ? "Speed limit (%)" : "Speed limit (bytes/s, 0 = unlimited)"}
            <span className="flex gap-2">
              <input
                value={limit}
                inputMode="numeric"
                onChange={(event) => setLimit(event.target.value)}
                className={`${CONTROL_HEIGHT.sm} w-32 rounded-md border border-border bg-bg px-2 text-sm`}
              />
              <Button
                size="sm"
                variant="secondary"
                disabled={pending}
                onClick={() => {
                  const parsed = Number.parseInt(limit, 10);
                  if (!Number.isFinite(parsed) || parsed < 0) {
                    setError("Speed limit must be zero or a positive whole number.");
                    return;
                  }
                  act(() => setSpeedLimit(instanceId, parsed));
                }}
              >
                Apply
              </Button>
            </span>
          </label>

          <span className="ml-auto text-sm text-muted">
            {formatBytes(queue.speed_bytes)}/s
            {queue.paused && " · paused"}
          </span>
        </div>

        {error && (
          <p role="alert" className="mt-2 text-sm text-error">
            {error}
          </p>
        )}
      </Card>

      <Card title={`Queue (${queue.items.length})`}>
        {queue.items.length === 0 ? (
          <p className="text-sm text-muted">The queue is empty.</p>
        ) : (
          <table className={CARD_TABLE.table}>
            <thead className={CARD_TABLE.thead}>
              <tr className="border-b border-border text-left">
                <th scope="col" className="px-3 py-2 font-medium text-muted">
                  Name
                </th>
                <th scope="col" className="px-3 py-2 font-medium text-muted">
                  Status
                </th>
                <th scope="col" className="px-3 py-2 font-medium text-muted">
                  Progress
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium text-muted">
                  Size
                </th>
                <th scope="col" className="px-3 py-2 font-medium text-muted">
                  ETA
                </th>
                <th scope="col" className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className={CARD_TABLE.tbody}>
              {queue.items.map((item) => (
                <tr key={item.id} className={CARD_TABLE.row}>
                  <td
                    className={cn(CARD_TABLE.lead, "max-w-md truncate max-lg:max-w-none")}
                    title={item.name}
                  >
                    {item.name}
                  </td>
                  <td data-label="Status" className={CARD_TABLE.cell}>
                    {item.status}
                  </td>
                  <td data-label="Progress" className={CARD_TABLE.cell}>
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-24 rounded-full bg-border">
                        <span
                          className="block h-full rounded-full bg-accent"
                          style={{ width: `${item.progress_pct}%` }}
                        />
                      </span>
                      <span className="tabular-nums text-xs text-muted">
                        {item.progress_pct}%
                      </span>
                    </span>
                  </td>
                  <td
                    data-label="Size"
                    className={cn(CARD_TABLE.cell, "text-right tabular-nums")}
                  >
                    {formatBytes(item.size_bytes)}
                  </td>
                  <td data-label="ETA" className={cn(CARD_TABLE.cell, "text-muted")}>
                    {formatEta(item.eta)}
                  </td>
                  <td className={CARD_TABLE.bare}>
                    <span className="flex justify-end gap-2 max-lg:pt-1">
                      {perItemPause && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={pending}
                          onClick={() =>
                            act(() =>
                              item.status.toLowerCase().startsWith("pause")
                                ? resumeItem(instanceId, item.id)
                                : pauseItem(instanceId, item.id),
                            )
                          }
                        >
                          {item.status.toLowerCase().startsWith("pause")
                            ? "Resume"
                            : "Pause"}
                        </Button>
                      )}
                      {isSab && (
                        <Button
                          size="sm"
                          variant="danger"
                          disabled={pending}
                          onClick={() => {
                            if (
                              !window.confirm(`Remove "${item.name}" from the queue?`)
                            ) {
                              return;
                            }
                            act(() => deleteItem(instanceId, item.id));
                          }}
                        >
                          Delete
                        </Button>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
