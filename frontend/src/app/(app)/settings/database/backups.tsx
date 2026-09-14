"use client";

import { useCallback, useEffect, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { clientFetch } from "@/lib/client-fetch";
import { formatBytes, formatDateTime } from "@/lib/format";

type Backup = { name: string; size: number; modified: number };

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; backups: Backup[] };

export function Backups() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await clientFetch<{ backups: Backup[] }>("/api/database/backups", {
        signal,
      });
      if (!signal?.aborted) setState({ status: "ok", backups: data.backups });
    } catch (caught) {
      if (signal?.aborted) return;
      setState({
        status: "error",
        message: caught instanceof Error ? caught.message : "Failed to load backups",
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function create() {
    setError(null);
    startTransition(async () => {
      try {
        await clientFetch("/api/database/backups", { method: "POST" });
        await load();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Backup failed");
      }
    });
  }

  return (
    <Card
      title="Backups"
      actions={
        <Button size="sm" onClick={create} disabled={pending}>
          {pending ? "Creating…" : "Create backup"}
        </Button>
      }
    >
      <p className="mb-3 text-sm text-muted">
        Backups contain API keys and password hashes, so they are written readable only by
        the owning user.
      </p>

      {error && (
        <p role="alert" className="mb-2 text-sm text-error">
          {error}
        </p>
      )}

      {state.status === "loading" && <Spinner label="Loading backups…" />}

      {state.status === "error" && (
        <p role="alert" className="text-sm text-error">
          {state.message}
        </p>
      )}

      {state.status === "ok" &&
        (state.backups.length === 0 ? (
          <p className="text-sm text-muted">No backups yet.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {state.backups.map((backup) => (
              <li
                key={backup.name}
                className="flex items-center justify-between gap-4 py-2 text-sm"
              >
                <span className="truncate font-mono text-xs">{backup.name}</span>
                <span className="shrink-0 text-muted">
                  {formatDateTime(new Date(backup.modified * 1000).toISOString())}
                </span>
                <span className="shrink-0 tabular-nums text-muted">
                  {formatBytes(backup.size)}
                </span>
                <a
                  href={`/api/database/backups/${encodeURIComponent(backup.name)}`}
                  download
                  className="shrink-0 text-accent hover:underline"
                >
                  Download
                </a>
              </li>
            ))}
          </ul>
        ))}
    </Card>
  );
}
