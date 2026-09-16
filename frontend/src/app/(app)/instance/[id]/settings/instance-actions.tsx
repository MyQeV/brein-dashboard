"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EXTRA_PINGABLE, EXTRA_RESTARTABLE } from "@/extras";
import type { ActionResult } from "@/lib/actions";
import { pingInstance, restartInstance } from "./actions";

const RESTARTABLE = new Set([
  "emby",
  "jellyfin",
  "sonarr",
  "radarr",
  "sabnzbd",
  ...EXTRA_RESTARTABLE,
]);

// Only these have a ping route. The button used to render for every service,
// so on Plex and the other clients without one "Test reachability" always
// answered "Not Found" — which reads as the server being down.
const PINGABLE = new Set([
  "emby",
  "jellyfin",
  "sonarr",
  "radarr",
  "sabnzbd",
  ...EXTRA_PINGABLE,
]);

export function InstanceActions({
  instanceId,
  serviceType,
}: {
  instanceId: number;
  serviceType: string;
}) {
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  function run(action: () => Promise<ActionResult>) {
    startTransition(async () => setResult(await action()));
  }

  return (
    <Card title="Actions">
      <div className="flex flex-wrap items-center gap-3">
        {PINGABLE.has(serviceType) && (
          <Button
            variant="secondary"
            disabled={pending}
            onClick={() => run(() => pingInstance(instanceId, serviceType))}
          >
            Test reachability
          </Button>
        )}

        {RESTARTABLE.has(serviceType) && (
          <Button
            variant="danger"
            disabled={pending}
            onClick={() => {
              // Restarting someone's media server mid-stream is worth one
              // confirmation.
              if (!window.confirm(`Restart ${serviceType}? Active streams will drop.`)) {
                return;
              }
              run(() => restartInstance(instanceId, serviceType));
            }}
          >
            Restart
          </Button>
        )}

        {result && (
          <span
            role={result.ok ? "status" : "alert"}
            className={result.ok ? "text-sm text-success" : "text-sm text-error"}
          >
            {result.ok ? (result.message ?? "Done.") : result.error}
          </span>
        )}
      </div>
    </Card>
  );
}
