"use client";

import { useMemo, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import type { ScheduledTask } from "@/lib/types";
import { runTaskNow, setTaskEnabled, setTaskInterval } from "./actions";

const MIN_INTERVAL = 5;
const MAX_INTERVAL = 86400;

function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0 && seconds >= 3600) return `${seconds / 3600}h`;
  if (seconds % 60 === 0 && seconds >= 60) return `${seconds / 60}m`;
  return `${seconds}s`;
}

function TaskRow({
  task,
  onError,
}: {
  task: ScheduledTask;
  onError: (message: string | null) => void;
}) {
  const [interval, setIntervalValue] = useState(String(task.interval_seconds));
  const [pending, startTransition] = useTransition();

  function act(action: () => Promise<{ ok: boolean; error?: string }>) {
    onError(null);
    startTransition(async () => {
      const result = await action();
      if (!result.ok) onError(result.error ?? "Action failed");
    });
  }

  function commitInterval() {
    const parsed = Number.parseInt(interval, 10);
    if (!Number.isFinite(parsed) || parsed < MIN_INTERVAL || parsed > MAX_INTERVAL) {
      onError(`Interval must be between ${MIN_INTERVAL} and ${MAX_INTERVAL} seconds.`);
      setIntervalValue(String(task.interval_seconds));
      return;
    }
    if (parsed === task.interval_seconds) return;
    act(() => setTaskInterval(task.id, parsed));
  }

  return (
    <tr className="border-b border-border">
      <td className="px-3 py-2">
        <span className="block">{task.name}</span>
        <span className="block font-mono text-xs text-muted">{task.key}</span>
      </td>
      <td className="px-3 py-2">
        <input
          value={interval}
          inputMode="numeric"
          aria-label={`Interval in seconds for ${task.name}`}
          disabled={pending}
          onChange={(event) => setIntervalValue(event.target.value)}
          onBlur={commitInterval}
          className={`${CONTROL_HEIGHT.sm} w-24 rounded-md border border-border bg-bg px-2 text-sm`}
        />
        <span className="ml-2 text-xs text-muted">
          {formatInterval(task.interval_seconds)}
        </span>
      </td>
      <td className="px-3 py-2">
        <span
          className={cn(
            "text-sm",
            task.last_status === "success"
              ? "text-success"
              : task.last_status
                ? "text-error"
                : "text-muted",
          )}
        >
          {task.is_running ? "Running" : (task.last_status ?? "never run")}
        </span>
      </td>
      <td className="px-3 py-2 text-sm text-muted">{formatDateTime(task.last_run_at)}</td>
      <td className="px-3 py-2 text-sm text-muted">{formatDateTime(task.next_due_at)}</td>
      <td className="px-3 py-2">
        <div className="flex justify-end gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={pending}
            onClick={() => act(() => runTaskNow(task.id))}
          >
            Run now
          </Button>
          <Button
            size="sm"
            variant={task.enabled ? "ghost" : "secondary"}
            disabled={pending}
            onClick={() => act(() => setTaskEnabled(task.id, !task.enabled))}
          >
            {task.enabled ? "Enabled" : "Disabled"}
          </Button>
        </div>
      </td>
    </tr>
  );
}

export function TasksView({ tasks }: { tasks: ScheduledTask[] }) {
  const [error, setError] = useState<string | null>(null);

  // Globals first, then one group per instance. The Jinja handler did this
  // server-side; the API returns flat rows and leaves the grouping here.
  const groups = useMemo(() => {
    const global = tasks.filter((task) => task.instance_id === null);
    const byInstance = new Map<number, ScheduledTask[]>();
    for (const task of tasks) {
      if (task.instance_id === null) continue;
      const list = byInstance.get(task.instance_id);
      if (list) list.push(task);
      else byInstance.set(task.instance_id, [task]);
    }
    return [
      ...(global.length > 0 ? [{ key: "global", label: "Global", tasks: global }] : []),
      ...[...byInstance.entries()]
        .sort(([a], [b]) => a - b)
        .map(([id, list]) => ({
          key: String(id),
          label: list[0]?.instance_label ?? `Instance ${id}`,
          tasks: list,
        })),
    ];
  }, [tasks]);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        The scheduler reads these intervals directly — this is the only place a
        task&apos;s cadence is set. Changes take effect on the next poll.
      </p>

      {error && (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      )}

      {/* Keyed by instance, not label: two servers can share a label, and React
          would then reuse one card's subtree — including its inline interval
          edits — for the other. */}
      {groups.map((group) => (
        <Card key={group.key} title={group.label}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-left">
                  <th scope="col" className="px-3 py-2 font-medium text-muted">
                    Task
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium text-muted">
                    Interval (s)
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium text-muted">
                    Status
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium text-muted">
                    Last run
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium text-muted">
                    Next due
                  </th>
                  <th scope="col" className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {group.tasks.map((task) => (
                  <TaskRow key={task.id} task={task} onError={setError} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  );
}
