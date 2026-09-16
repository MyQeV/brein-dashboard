import type { Metadata } from "next";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { Card } from "@/components/ui/card";
import { ReadOnlyField } from "@/components/ui/field";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime, formatInterval } from "@/lib/format";
import { appTimeZone } from "@/lib/timezone";
import type { TaskDetail, TaskRun } from "@/lib/types";

export const metadata: Metadata = { title: "Task" };

function formatDurationMs(value: number | null): string {
  if (value === null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`;
}

export default async function TaskDetailPage(props: PageProps<"/settings/tasks/[id]">) {
  const { id } = await props.params;
  const { task, runs } = await apiFetch<{ task: TaskDetail; runs: TaskRun[] }>(
    `/api/tasks/${encodeURIComponent(id)}`,
  );
  const timeZone = appTimeZone();

  return (
    <div className="flex flex-col gap-4">
      <Link href="/settings/tasks" className="text-sm text-muted hover:text-text">
        ← Back to tasks
      </Link>

      <Card title={task.name}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <ReadOnlyField label="Key" value={task.key} />
          <ReadOnlyField
            label="Interval"
            value={`${task.interval_seconds}s (${formatInterval(task.interval_seconds)})`}
          />
          <ReadOnlyField
            label="State"
            value={task.is_running ? "Running" : task.enabled ? "Enabled" : "Disabled"}
          />
          <ReadOnlyField
            label="Last run"
            value={formatDateTime(task.last_run_at, timeZone)}
          />
        </div>
      </Card>

      <Card title="Recent runs">
        <DataTable<TaskRun>
          rows={runs}
          cards
          rowKey={(run) => String(run.id)}
          empty="This task has not run yet."
          columns={[
            {
              key: "started_at",
              header: "Started",
              render: (run) => formatDateTime(run.started_at, timeZone),
            },
            {
              key: "status",
              header: "Status",
              render: (run) => (
                <span
                  className={cn(
                    run.status === "success"
                      ? "text-success"
                      : run.status
                        ? "text-error"
                        : "text-muted",
                  )}
                >
                  {run.status ?? "—"}
                </span>
              ),
            },
            {
              key: "duration_ms",
              header: "Duration",
              align: "right",
              render: (run) => formatDurationMs(run.duration_ms),
            },
            {
              key: "error_message",
              header: "Error",
              // A details toggle rather than a row underneath: the table is
              // server-rendered, and a native <details> opens without any
              // script — on a phone card as well as in the table.
              render: (run) =>
                run.error_message ? (
                  <details className="max-w-full">
                    <summary className="cursor-pointer text-accent">
                      Show traceback
                    </summary>
                    <pre className="mt-2 max-h-64 max-w-full overflow-auto rounded-md border border-border bg-bg p-3 font-mono text-xs whitespace-pre-wrap">
                      {run.error_message}
                    </pre>
                  </details>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
