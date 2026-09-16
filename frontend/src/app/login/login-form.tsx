"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { errorDetail } from "@/lib/client-fetch";

/**
 * Only ever follow a same-origin path, never an absolute URL from the query.
 *
 * A leading `//` is a scheme-relative URL, and browsers read `/\` the same
 * way — so `next=/\evil.com` would have left the site.
 */
function safeNext(value: string | null): string {
  if (!value?.startsWith("/")) return "/";
  return value.startsWith("//") || value.startsWith("/\\") ? "/" : value;
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // Start in "checking" so a returning user with a live refresh token is not
  // shown a form they never needed.
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // A fresh install has no users, so the login form here can never succeed.
    // The proxy's auth gate only sees cookies, so it cannot know that.
    fetch("/api/setup-status", { credentials: "include" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { setup_required?: boolean } | null) => {
        if (!cancelled && data?.setup_required) router.replace("/setup");
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    let cancelled = false;
    fetch("/refresh", { method: "POST", credentials: "include" })
      .then((response) => {
        if (cancelled) return;
        if (response.ok) router.replace(next);
        else setChecking(false);
      })
      .catch(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [router, next]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);

    // Posted same-origin through the proxy, so the browser stores the cookies
    // /token sets. No token in localStorage, and no /set-session-cookie hop.
    const body = new URLSearchParams({ username, password });
    if (remember) body.set("remember_me", "true");

    try {
      const response = await fetch("/token", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body,
      });
      if (!response.ok) {
        setError((await errorDetail(response)) ?? "Incorrect username or password.");
        setPending(false);
        return;
      }
      router.replace(next);
      router.refresh();
    } catch {
      setError("Could not reach the server.");
      setPending(false);
    }
  }

  if (checking) {
    return (
      <Card>
        <Spinner label="Signing in…" />
      </Card>
    );
  }

  return (
    <Card title="Sign in to Brein" className="w-full max-w-sm">
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
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={pending}
          required
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={remember}
            onChange={(event) => setRemember(event.target.checked)}
            disabled={pending}
          />
          Remember me
        </label>

        {error && (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        )}

        <Button type="submit" disabled={pending}>
          {pending ? "Signing in…" : "Log in"}
        </Button>
      </form>
    </Card>
  );
}
