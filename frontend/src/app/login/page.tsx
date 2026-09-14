import type { Metadata } from "next";
import { Suspense } from "react";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="grid min-h-dvh place-items-center p-6">
      {/* useSearchParams() reads the `next` param, so the form cannot be
          prerendered; the boundary lets the rest of the page be. */}
      <Suspense
        fallback={
          <Card>
            <Spinner label="Loading…" />
          </Card>
        }
      >
        <LoginForm />
      </Suspense>
    </main>
  );
}
