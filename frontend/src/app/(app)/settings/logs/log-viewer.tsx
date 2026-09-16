"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { clientFetch } from "@/lib/client-fetch";

type LogFile = { name: string; size: number; modified: number };

const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"] as const;
const MAX_LINES = 500;

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; lines: string[] };

function buildQuery(input: {
  file: string;
  level: string;
  search: string;
  lines?: number;
}): string {
  const params = new URLSearchParams();
  if (input.file) params.set("file", input.file);
  if (input.level && input.level !== "ALL") params.set("level", input.level);
  if (input.search) params.set("search", input.search);
  if (input.lines) params.set("lines", String(input.lines));
  return params.toString();
}

export function LogViewer() {
  const [files, setFiles] = useState<LogFile[]>([]);
  const [file, setFile] = useState("");
  const [level, setLevel] = useState<string>("ALL");
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState(200);
  const [state, setState] = useState<State>({ status: "loading" });

  // Guards against an older, slower response overwriting a newer one — type
  // "err" then "error" quickly and the first request can land last.
  const requestSeq = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    clientFetch<{ files: LogFile[] }>("/api/settings/logs/files", {
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        setFiles(data.files);
        setFile((current) => current || (data.files[0]?.name ?? ""));
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setState({ status: "loading" });
    try {
      const query = buildQuery({ file, level, search, lines });
      const data = await clientFetch<{ lines: string[] }>(
        `/api/settings/logs/view?${query}`,
      );
      if (seq === requestSeq.current) setState({ status: "ok", lines: data.lines });
    } catch (error) {
      if (seq !== requestSeq.current) return;
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Failed to load logs",
      });
    }
  }, [file, level, search, lines]);

  useEffect(() => {
    if (!file) return;
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load, file]);

  return (
    <Card
      title="Log viewer"
      actions={
        <a
          href={`/api/settings/logs/download?${buildQuery({ file, level, search })}`}
          className="text-sm text-muted hover:text-text"
        >
          Download
        </a>
      }
    >
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label htmlFor="log-file" className="flex flex-col gap-1 text-sm">
          File
          <Select
            id="log-file"
            size="sm"
            value={file}
            onChange={(event) => setFile(event.target.value)}
          >
            {files.map((entry) => (
              <option key={entry.name} value={entry.name}>
                {entry.name} ({Math.round(entry.size / 1024)} KB)
              </option>
            ))}
          </Select>
        </label>

        <label htmlFor="log-level" className="flex flex-col gap-1 text-sm">
          Level
          <Select
            id="log-level"
            size="sm"
            value={level}
            onChange={(event) => setLevel(event.target.value)}
          >
            {LEVELS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          Search
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Filter lines…"
            className={`${CONTROL_HEIGHT.sm} rounded-md border border-border bg-bg px-2 text-sm`}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          Lines
          <input
            type="number"
            min={1}
            max={MAX_LINES}
            value={lines}
            onChange={(event) => {
              const parsed = Number.parseInt(event.target.value, 10);
              // The API caps at 500; clamp here so the control cannot ask for
              // more and silently get fewer.
              setLines(
                Number.isFinite(parsed) ? Math.min(Math.max(parsed, 1), MAX_LINES) : 200,
              );
            }}
            className={`${CONTROL_HEIGHT.sm} w-24 rounded-md border border-border bg-bg px-2 text-sm`}
          />
        </label>

        <Button size="sm" variant="secondary" onClick={load}>
          Refresh
        </Button>
      </div>

      {state.status === "loading" && <Spinner label="Loading logs…" />}

      {state.status === "error" && (
        <p role="alert" className="text-sm text-error">
          {state.message}
        </p>
      )}

      {state.status === "ok" && (
        <pre className="max-h-[60vh] overflow-auto rounded-md border border-border bg-bg p-3 font-mono text-xs">
          {state.lines.length > 0 ? state.lines.join("\n") : "(no matching lines)"}
        </pre>
      )}
    </Card>
  );
}
