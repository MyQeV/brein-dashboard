"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/lib/actions";
import type { ArrTab } from "@/lib/arr-tabs";
import { runCommand, testAll as testAllAction } from "./actions";

/**
 * The upstream commands a tab can trigger, as buttons in its header.
 *
 * The API has proxied /command since it was written and nothing called it, so
 * kicking off a search or an RSS sync meant opening Sonarr or Radarr itself.
 * These run in the background upstream — a success here means the command was
 * accepted, which is why the confirmation says "started" rather than "done".
 */
export function TabActions({
  instanceId,
  service,
  tab,
  endpoint,
  commands,
  testAll,
}: {
  instanceId: number;
  service: string;
  tab: string;
  endpoint: string;
  commands: NonNullable<ArrTab["commands"]>;
  testAll?: boolean;
}) {
  const [result, setResult] = useState<ActionResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function run(label: string, action: () => Promise<ActionResult>) {
    setResult(null);
    setRunning(label);
    startTransition(async () => {
      const outcome = await action();
      setResult(outcome);
      setRunning(null);
    });
  }

  if (commands.length === 0 && !testAll) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {testAll && (
        <Button
          size="sm"
          variant="secondary"
          disabled={pending}
          onClick={() =>
            run("Test all", () => testAllAction(instanceId, service, endpoint, tab))
          }
        >
          {running === "Test all" ? "Testing…" : "Test all indexers"}
        </Button>
      )}
      {commands.map((command) => (
        <Button
          key={command.name}
          size="sm"
          variant="secondary"
          disabled={pending}
          onClick={() =>
            run(command.label, () => runCommand(instanceId, service, command.name, tab))
          }
        >
          {running === command.label ? "Starting…" : command.label}
        </Button>
      ))}
      {result && !result.ok && (
        <span role="alert" className="text-sm text-error">
          {result.error}
        </span>
      )}
      {result?.ok && (
        <span role="status" className="text-sm text-success">
          Started.
        </span>
      )}
    </div>
  );
}
