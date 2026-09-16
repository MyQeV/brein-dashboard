"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import type { InstanceDetail } from "@/lib/types";
import {
  createInstance,
  deleteInstance,
  saveInstance,
  testConnection,
  testInstance,
} from "../actions";

type Props =
  | { instance: InstanceDetail; serviceType?: undefined; serviceName?: undefined }
  /** No instance yet: the form creates one, and only after its test passed. */
  | { instance?: undefined; serviceType: string; serviceName: string };

export function InstanceForm({ instance, serviceType, serviceName }: Props) {
  const router = useRouter();
  const creating = instance === undefined;
  const [label, setLabel] = useState(instance?.label ?? "");
  const [host, setHost] = useState(instance?.host ?? "");
  const [port, setPort] = useState(
    instance?.port === undefined || instance.port === null ? "" : String(instance.port),
  );
  const [apiKey, setApiKey] = useState("");
  const [externalUrl, setExternalUrl] = useState(instance?.external_url ?? "");
  // Displayed one-based, stored zero-based. The Jinja form did the same but
  // its JSON sibling took the raw value, so the two disagreed by one.
  const [order, setOrder] = useState(String((instance?.sort_order ?? 0) + 1));
  const [active, setActive] = useState(instance?.active ?? true);

  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  // The connection a passing test was for. Save on a new app needs the
  // current host, port and key to match it, so editing any of them after the
  // test disables Save again until it is rerun.
  const [verified, setVerified] = useState<string | null>(null);
  const connection = `${host.trim()}|${port.trim()}|${apiKey}`;
  // What "Test connection" tries. With a key in the field it is the form's
  // values, stored or not. Without one the only key there is is the stored
  // one, and the API only pairs that with the stored host and port — so it
  // used to report the old server reachable after the host had been edited.
  // A changed host needs its key entered before it can be tested.
  const testsForm = creating || apiKey !== "";
  const hostChanged =
    !creating &&
    (host.trim() !== instance.host ||
      port.trim() !== (instance.port === null ? "" : String(instance.port)));
  const canTest =
    host.trim() !== "" &&
    (testsForm ? apiKey !== "" : instance.is_configured && !hostChanged);
  const testHint = canTest
    ? undefined
    : hostChanged
      ? "Enter the API key to test a changed host"
      : "Set a host and API key first";
  const canSave = creating ? verified === connection : true;

  const [pending, startTransition] = useTransition();
  const [testing, startTesting] = useTransition();

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      const zeroBased = order.trim() ? String(Math.max(0, Number(order) - 1)) : "";
      const input = {
        label,
        host,
        port,
        // On an existing app, empty means untouched: keep the stored key.
        api_key: apiKey,
        external_url: externalUrl,
        sort_order: zeroBased,
        active,
      };
      if (creating) {
        const result = await createInstance(serviceType, input);
        if (result.ok) {
          router.push("/settings/app");
          router.refresh();
        } else {
          setMessage({ ok: false, text: result.error });
        }
        return;
      }
      const result = await saveInstance(instance.id, input);
      setMessage(
        result.ok ? { ok: true, text: "Saved." } : { ok: false, text: result.error },
      );
      if (result.ok) {
        setApiKey("");
        router.refresh();
      }
    });
  }

  function onTest() {
    startTesting(async () => {
      const tested = connection;
      const result = testsForm
        ? await testConnection({
            service_type: creating ? serviceType : instance.service_type,
            host,
            port,
            api_key: apiKey,
          })
        : await testInstance(instance.id);
      setTestResult({ ok: result.ok, text: result.message });
      setVerified(result.ok ? tested : null);
    });
  }

  function onDelete() {
    if (creating) return;
    if (
      !window.confirm(`Delete "${instance.label ?? instance.id}"? This cannot be undone.`)
    ) {
      return;
    }
    startTransition(async () => {
      const result = await deleteInstance(instance.id);
      if (result.ok) router.push("/settings/app");
      else setMessage({ ok: false, text: result.error });
    });
  }

  return (
    <Card
      title={
        creating
          ? `New ${serviceName}`
          : `${instance.service_type} — ${instance.label ?? instance.id}`
      }
      actions={
        creating ? undefined : (
          <Button size="sm" variant="danger" onClick={onDelete} disabled={pending}>
            Delete
          </Button>
        )
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field
          label="Label"
          name="label"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          disabled={pending}
        />
        <Field
          label="Host"
          name="host"
          placeholder="192.168.1.10 or media.example.com"
          value={host}
          onChange={(event) => setHost(event.target.value)}
          disabled={pending}
        />
        <Field
          label="Port"
          name="port"
          inputMode="numeric"
          value={port}
          onChange={(event) => setPort(event.target.value)}
          disabled={pending}
        />
        <Field
          label="API key"
          name="api_key"
          type="password"
          autoComplete="off"
          placeholder={creating ? "Required" : instance.api_key_masked || "Not set"}
          help={creating ? undefined : "Leave blank to keep the stored key."}
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          disabled={pending}
        />
        <Field
          label="External URL"
          name="external_url"
          placeholder="https://sonarr.example.com"
          help="Used for the Open app link."
          value={externalUrl}
          onChange={(event) => setExternalUrl(event.target.value)}
          disabled={pending}
        />
        <Field
          label="Order"
          name="sort_order"
          inputMode="numeric"
          help="Position in the sidebar, starting at 1."
          value={order}
          onChange={(event) => setOrder(event.target.value)}
          disabled={pending}
        />

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(event) => setActive(event.target.checked)}
            disabled={pending}
          />
          Active
        </label>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            disabled={pending || !canSave}
            title={canSave ? undefined : "Test the connection first"}
          >
            {pending ? (creating ? "Adding…" : "Saving…") : creating ? "Add app" : "Save"}
          </Button>
          <Button
            variant="secondary"
            onClick={onTest}
            disabled={testing || !canTest}
            title={testHint}
          >
            {testing ? "Testing…" : "Test connection"}
          </Button>

          {message && (
            <span
              role={message.ok ? "status" : "alert"}
              className={message.ok ? "text-sm text-success" : "text-sm text-error"}
            >
              {message.text}
            </span>
          )}
          {testResult && (
            <span
              role="status"
              className={testResult.ok ? "text-sm text-success" : "text-sm text-error"}
            >
              {testResult.text}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
