"use server";

import { revalidatePath } from "next/cache";
import { type ActionResult, toResult } from "@/lib/actions";
import { apiFetch } from "@/lib/api";

async function call(
  instanceId: number,
  path: string,
  init: RequestInit,
): Promise<ActionResult> {
  try {
    await apiFetch(`/api/instances/${instanceId}/downloads${path}`, init);
  } catch (error) {
    return toResult(error);
  }
  revalidatePath(`/instance/${instanceId}/dl-queue`);
  return { ok: true };
}

export async function pauseQueue(instanceId: number) {
  return call(instanceId, "/pause", { method: "POST" });
}

export async function resumeQueue(instanceId: number) {
  return call(instanceId, "/resume", { method: "POST" });
}

export async function setSpeedLimit(instanceId: number, value: number) {
  return call(instanceId, "/speed-limit", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ value }),
  });
}

export async function pauseItem(instanceId: number, itemId: string) {
  return call(instanceId, `/items/${encodeURIComponent(itemId)}/pause`, {
    method: "POST",
  });
}

export async function resumeItem(instanceId: number, itemId: string) {
  return call(instanceId, `/items/${encodeURIComponent(itemId)}/resume`, {
    method: "POST",
  });
}

/**
 * Pause the queue and let it resume by itself after `minutes`.
 *
 * SABnzbd handles the timer, so this survives a Brein restart — which is what
 * makes it different from pausing and remembering to come back.
 */
export async function pauseQueueTimed(instanceId: number, minutes: number) {
  return call(instanceId, "/pause-timed", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ minutes }),
  });
}

export async function deleteItem(instanceId: number, itemId: string) {
  return call(instanceId, `/items/${encodeURIComponent(itemId)}`, {
    method: "DELETE",
  });
}

/** Retry every failed item in the history in one pass. */
export async function retryAllHistory(instanceId: number): Promise<ActionResult> {
  try {
    await apiFetch(`/api/instances/${instanceId}/downloads/history/retry-all`, {
      method: "POST",
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath(`/instance/${instanceId}/dl-history`);
  return { ok: true };
}

/**
 * Mark one failed history item as completed.
 *
 * For the download that did finish, by hand or elsewhere, and that the
 * downloader still lists as failed.
 */
export async function markHistoryCompleted(
  instanceId: number,
  itemId: string,
): Promise<ActionResult> {
  try {
    await apiFetch(
      `/api/instances/${instanceId}/downloads/history/${encodeURIComponent(itemId)}/mark-completed`,
      { method: "POST" },
    );
  } catch (error) {
    return toResult(error);
  }
  revalidatePath(`/instance/${instanceId}/dl-history`);
  return { ok: true };
}
