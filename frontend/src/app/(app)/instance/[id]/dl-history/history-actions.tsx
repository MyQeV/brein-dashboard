"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/lib/actions";
import { markHistoryCompleted, retryAllHistory } from "../dl-queue/actions";

/**
 * Retry every failed item, from the history header.
 *
 * The API has had `history/retry-all` since it was written and nothing called
 * it, so clearing a run of failures meant retrying them one at a time in
 * SABnzbd itself.
 */
export function RetryAllButton({
  instanceId,
  failedCount,
}: {
  instanceId: number;
  /** Only shown when there is something to retry. */
  failedCount: number;
}) {
  const router = useRouter();
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  if (failedCount === 0) return null;

  return (
    <div className="flex items-center gap-2">
      {result && !result.ok && (
        <span role="alert" className="text-sm text-error">
          {result.error}
        </span>
      )}
      <Button
        size="sm"
        variant="secondary"
        disabled={pending}
        onClick={() => {
          if (!window.confirm(`Retry ${failedCount} failed download(s)?`)) return;
          setResult(null);
          startTransition(async () => {
            const outcome = await retryAllHistory(instanceId);
            setResult(outcome);
            if (outcome.ok) router.refresh();
          });
        }}
      >
        {pending ? "Retrying…" : `Retry all failed (${failedCount})`}
      </Button>
    </div>
  );
}

/** Mark one failed item as completed — for a download that finished elsewhere. */
export function MarkCompletedButton({
  instanceId,
  itemId,
}: {
  instanceId: number;
  itemId: string;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <>
      <button
        type="button"
        disabled={pending}
        title="Mark as completed"
        onClick={() => {
          setError(null);
          startTransition(async () => {
            const outcome = await markHistoryCompleted(instanceId, itemId);
            if (outcome.ok) router.refresh();
            else setError(outcome.error);
          });
        }}
        className="cursor-pointer text-xs text-muted underline decoration-dotted hover:text-text disabled:cursor-default"
      >
        {pending ? "…" : "Mark done"}
      </button>
      {error && (
        <span role="alert" className="ml-2 text-xs text-error">
          {error}
        </span>
      )}
    </>
  );
}
