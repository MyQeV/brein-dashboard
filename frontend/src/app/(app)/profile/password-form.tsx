"use client";

import { useEffect, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import type { ActionResult } from "@/lib/actions";
import { signOut } from "@/lib/client-fetch";
import { changePassword } from "./actions";

const POLICY =
  "At least 10 characters with an upper case letter, a lower case letter, a digit and a symbol. Not your username or full name.";

/** Long enough to read the confirmation before the login page replaces it. */
const SIGN_OUT_DELAY_MS = 1500;

export function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  // The API revokes the refresh tokens and blacklists the access token that
  // made the change, so the next request would 401 and bounce to /login
  // with no explanation. Say so, then go there the way an expired session
  // does — a full navigation, with the way back to this page.
  const changed = result?.ok === true;
  useEffect(() => {
    if (!changed) return;
    const timer = window.setTimeout(signOut, SIGN_OUT_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [changed]);

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
          disabled={pending || changed}
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
          disabled={pending || changed}
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
          disabled={pending || changed}
          required
        />

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={pending || changed}>
            {pending ? "Changing…" : "Change password"}
          </Button>
          {changed && (
            <span role="status" className="text-sm text-success">
              Password changed — sign in again.
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
