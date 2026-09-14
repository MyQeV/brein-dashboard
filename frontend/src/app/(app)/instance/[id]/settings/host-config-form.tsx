"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { type ActionResult, saveHostConfig } from "./actions";

/** The subset the API accepts; anything else in the payload is read-only. */
const EDITABLE = [
  { key: "instanceName", label: "Instance name", type: "text" },
  { key: "applicationUrl", label: "Application URL", type: "text" },
  { key: "host", label: "Bind address", type: "text" },
  { key: "port", label: "Port", type: "number" },
  { key: "urlBase", label: "URL base", type: "text" },
  { key: "sslPort", label: "SSL port", type: "number" },
] as const;

export function HostConfigForm({
  instanceId,
  serviceType,
  config,
}: {
  instanceId: number;
  serviceType: string;
  config: Record<string, unknown>;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      EDITABLE.map(({ key }) => [key, config[key] == null ? "" : String(config[key])]),
    ),
  );
  const [enableSsl, setEnableSsl] = useState(Boolean(config.enableSsl));
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      const patch: Record<string, string | number | boolean | null> = {
        enableSsl,
      };
      for (const { key, type } of EDITABLE) {
        const raw = values[key] ?? "";
        if (raw === "") continue;
        if (type === "number") {
          const parsed = Number.parseInt(raw, 10);
          if (!Number.isFinite(parsed)) {
            setResult({ ok: false, error: `${key} must be a whole number.` });
            return;
          }
          patch[key] = parsed;
        } else {
          patch[key] = raw;
        }
      }
      setResult(await saveHostConfig(instanceId, serviceType, patch));
    });
  }

  return (
    <Card title="Host configuration">
      <p className="mb-3 text-sm text-muted">
        Changes are written to {serviceType} and usually require it to restart.
      </p>
      <form onSubmit={onSubmit} className="flex max-w-md flex-col gap-4">
        {EDITABLE.map(({ key, label, type }) => (
          <Field
            key={key}
            label={label}
            name={key}
            inputMode={type === "number" ? "numeric" : undefined}
            value={values[key] ?? ""}
            onChange={(event) =>
              setValues((current) => ({ ...current, [key]: event.target.value }))
            }
            disabled={pending}
          />
        ))}

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enableSsl}
            onChange={(event) => setEnableSsl(event.target.checked)}
            disabled={pending}
          />
          Enable SSL
        </label>

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : "Save host config"}
          </Button>
          {result && (
            <span
              role={result.ok ? "status" : "alert"}
              className={result.ok ? "text-sm text-success" : "text-sm text-error"}
            >
              {result.ok ? (result.message ?? "Saved.") : result.error}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
