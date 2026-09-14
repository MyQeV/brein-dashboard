"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";

const POLICY =
  "At least 10 characters with an upper case letter, a lower case letter, a digit and a symbol. Not your username.";

export function SetupForm() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/setup", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          username,
          password,
          email: email.trim() || null,
        }),
      });
      if (!response.ok) {
        const detail = await response
          .json()
          .then((data: { detail?: string }) => data.detail)
          .catch(() => undefined);
        setError(detail ?? "Could not create the administrator account.");
        setPending(false);
        return;
      }
      router.replace("/login");
    } catch {
      setError("Could not reach the server.");
      setPending(false);
    }
  }

  return (
    <Card title="Create the first administrator" className="w-full max-w-sm">
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field
          label="Username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          disabled={pending}
          required
        />
        <Field
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          help="Optional."
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={pending}
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={10}
          help={POLICY}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={pending}
          required
        />
        <Field
          label="Confirm password"
          name="confirm"
          type="password"
          autoComplete="new-password"
          minLength={10}
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          disabled={pending}
          required
        />

        {error && (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        )}

        <Button type="submit" disabled={pending}>
          {pending ? "Creating…" : "Create account"}
        </Button>
      </form>
    </Card>
  );
}
