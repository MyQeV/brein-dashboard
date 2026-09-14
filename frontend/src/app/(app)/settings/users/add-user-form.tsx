"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { Field } from "@/components/ui/field";
import { createUser } from "./actions";

const ROLES = ["user", "viewer", "admin"] as const;

export function AddUserForm() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<string>("user");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function reset() {
    setUsername("");
    setPassword("");
    setEmail("");
    setFullName("");
    setRole("user");
    setError(null);
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      const result = await createUser({
        username,
        password,
        email,
        full_name: fullName,
        role,
      });
      if (result.ok) {
        reset();
        setOpen(false);
        router.refresh();
      } else {
        setError(result.error);
      }
    });
  }

  if (!open) {
    return (
      <div>
        <Button
          onClick={() => {
            // Reset on open so a previous abandoned attempt is not still sitting
            // in the fields.
            reset();
            setOpen(true);
          }}
        >
          Add user
        </Button>
      </div>
    );
  }

  return (
    <Card title="Add user">
      <form onSubmit={onSubmit} className="flex max-w-md flex-col gap-4">
        <Field
          label="Username"
          name="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          disabled={pending}
          required
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={10}
          help="At least 10 characters with upper, lower, a digit and a symbol."
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={pending}
          required
        />
        <Field
          label="Email"
          name="email"
          type="email"
          help="Optional."
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={pending}
        />
        <Field
          label="Full name"
          name="full_name"
          help="Optional."
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          disabled={pending}
        />
        <label className="flex flex-col gap-1 text-sm font-medium">
          Role
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
            disabled={pending}
            className={`${CONTROL_HEIGHT.md} rounded-md border border-border bg-bg px-3 text-sm`}
          >
            {ROLES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        {error && (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        )}

        <div className="flex gap-2">
          <Button type="submit" disabled={pending}>
            {pending ? "Creating…" : "Create user"}
          </Button>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
