"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { type ActionResult, changePassword } from "./actions";

const POLICY =
  "At least 10 characters with an upper case letter, a lower case letter, a digit and a symbol. Not your username or full name.";

export function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    // Checked here so the mismatch case never costs a round trip; the server
    // remains the authority on the policy itself.
    if (next !== confirm) {
      setResult({ ok: false, error: "The new passwords do not match." });
      return;
    }
    startTransition(async () => {
      const outcome = await changePassword({
        current_password: current,
        new_password: next,
      });
      setResult(outcome);
      if (outcome.ok) {
        setCurrent("");
        setNext("");
        setConfirm("");
      }
    });
  }

  return (
    <Card title="Change password">
      <form onSubmit={onSubmit} className="flex max-w-md flex-col gap-4">
        <Field
          label="Current password"
          name="current_password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          disabled={pending}
          required
        />
        <Field
          label="New password"
          name="new_password"
          type="password"
          autoComplete="new-password"
          minLength={10}
          help={POLICY}
          value={next}
          onChange={(event) => setNext(event.target.value)}
          disabled={pending}
          required
        />
        <Field
          label="Confirm new password"
          name="confirm_password"
          type="password"
          autoComplete="new-password"
          minLength={10}
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          disabled={pending}
          required
        />

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={pending}>
            {pending ? "Changing…" : "Change password"}
          </Button>
          {result?.ok === true && (
            <span role="status" className="text-sm text-success">
              Password changed.
            </span>
          )}
          {result?.ok === false && (
            <span role="alert" className="text-sm text-error">
              {result.error}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
