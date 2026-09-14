"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import type { SystemSetting } from "@/lib/types";
import { type SaveResult, saveSettings } from "./actions";

export function ConfigForm({ settings }: { settings: SystemSetting[] }) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(settings.map((entry) => [entry.key, String(entry.current)])),
  );
  const [result, setResult] = useState<SaveResult | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      setResult(await saveSettings(values));
    });
  }

  return (
    <Card title="System settings">
      <p className="mb-4 text-sm text-muted">
        Scheduled job intervals are not here: they are set per task under Settings →
        Tasks, which is what the scheduler actually reads.
      </p>

      <form onSubmit={onSubmit} className="flex max-w-lg flex-col gap-4">
        {settings.map((entry) => (
          <Field
            key={entry.key}
            label={entry.unit ? `${entry.label} (${entry.unit})` : entry.label}
            name={entry.key}
            inputMode={entry.value_type === "str" ? undefined : "numeric"}
            help={entry.description}
            value={values[entry.key] ?? ""}
            onChange={(event) =>
              setValues((current) => ({ ...current, [entry.key]: event.target.value }))
            }
            disabled={pending}
          />
        ))}

        {result?.ok === false && (
          <ul role="alert" className="flex flex-col gap-1 text-sm text-error">
            {result.errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : "Save settings"}
          </Button>
          {result?.ok === true && (
            <span role="status" className="text-sm text-success">
              Saved.
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
