"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, ReadOnlyField } from "@/components/ui/field";
import type { ActionResult } from "@/lib/actions";
import type { User } from "@/lib/types";
import { saveProfile } from "./actions";

export function ProfileForm({ user }: { user: User }) {
  const [email, setEmail] = useState(user.email ?? "");
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      setResult(await saveProfile({ email, full_name: fullName }));
    });
  }

  return (
    <Card title="Profile">
      <form onSubmit={onSubmit} className="flex max-w-md flex-col gap-4">
        <ReadOnlyField label="Username" value={user.username} />
        <Field
          label="Email"
          name="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={pending}
        />
        <Field
          label="Full name"
          name="full_name"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          disabled={pending}
        />

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : "Save profile"}
          </Button>
          {result?.ok === true && (
            <span role="status" className="text-sm text-success">
              Saved.
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
