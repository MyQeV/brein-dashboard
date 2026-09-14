"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiFetch, isRedirectError } from "@/lib/api";

export type ActionResult = { ok: true } | { ok: false; error: string };

function toResult(error: unknown): ActionResult {
  if (isRedirectError(error)) throw error;
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

/**
 * Delete the selected rows of an *arr list tab.
 *
 * `endpoint` comes from the tab's own `bulkDelete` declaration in
 * lib/arr-tabs.ts rather than from the caller, so a client cannot aim this at
 * an arbitrary path; the API is admin-gated either way.
 */
export async function bulkDeleteRows(
  instanceId: number,
  service: string,
  endpoint: string,
  ids: number[],
  body: Record<string, unknown> = {},
  tab = "",
): Promise<ActionResult> {
  if (ids.length === 0) return { ok: true };
  try {
    await apiFetch(`/api/instances/${instanceId}/${service}/${endpoint}`, {
      method: "DELETE",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids, ...body }),
    });
  } catch (error) {
    return toResult(error);
  }
  if (tab) revalidatePath(`/instance/${instanceId}/${tab}`);
  return { ok: true };
}

/**
 * Trigger an upstream command (RSS sync, a search, a refresh).
 *
 * The *arr APIs take these as `{name: "..."}` on /command and run them in the
 * background, so a 200 means accepted, not finished.
 */
export async function runCommand(
  instanceId: number,
  service: string,
  name: string,
  tab = "",
): Promise<ActionResult> {
  try {
    await apiFetch(`/api/instances/${instanceId}/${service}/command`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
  } catch (error) {
    return toResult(error);
  }
  if (tab) revalidatePath(`/instance/${instanceId}/${tab}`);
  return { ok: true };
}

/**
 * Test every configured entry of this tab in one pass, for tabs that declare
 * `testAll`. `endpoint` comes from the tab's config, so the path is
 * `{service}/{endpoint}/testall` rather than anything the caller chooses.
 */
export async function testAll(
  instanceId: number,
  serviceType: string,
  endpoint: string,
  tab: string,
): Promise<ActionResult> {
  try {
    await apiFetch(`/api/instances/${instanceId}/${serviceType}/${endpoint}/testall`, {
      method: "POST",
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath(`/instance/${instanceId}/${tab}`);
  return { ok: true };
}
