"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/**
 * Without this, a failed API call renders Next's default error screen, which
 * says nothing useful and loses the surrounding chrome. A 403 in particular
 * is an expected outcome, not a crash.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // "admin" used to count here, which classified any error whose message
  // merely mentioned an admin as a permissions problem — and that branch hides
  // the retry button, turning a transient failure into a dead end.
  const forbidden = /\b403\b|forbidden/i.test(error.message);

  return (
    <Card title={forbidden ? "Not available" : "Something went wrong"}>
      <p className="mb-3 text-sm text-muted">
        {forbidden
          ? "This section needs administrator access."
          : error.message || "The request failed."}
      </p>
      {!forbidden && (
        <Button variant="secondary" onClick={reset}>
          Try again
        </Button>
      )}
    </Card>
  );
}
