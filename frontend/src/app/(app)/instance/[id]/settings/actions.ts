"use server";

import { revalidatePath } from "next/cache";
import { type ActionResult, toResult } from "@/lib/actions";
import { apiFetch } from "@/lib/api";

/** Only the *arrs expose a host config; the media servers do not. */
export async function saveHostConfig(
  instanceId: number,
  serviceType: string,
  patch: Record<string, string | number | boolean | null>,
): Promise<ActionResult> {
  try {
    await apiFetch(`/api/instances/${instanceId}/${serviceType}/config/host`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath(`/instance/${instanceId}/settings`);
  return { ok: true, message: "Saved." };
}

export async function pingInstance(
  instanceId: number,
  serviceType: string,
): Promise<ActionResult> {
  const path =
    serviceType === "emby" || serviceType === "jellyfin"
      ? `/api/instances/${instanceId}/media/ping`
      : `/api/instances/${instanceId}/${serviceType}/ping`;
  try {
    await apiFetch(path);
  } catch (error) {
    return toResult(error);
  }
  return { ok: true, message: "Reachable." };
}

export async function restartInstance(
  instanceId: number,
  serviceType: string,
): Promise<ActionResult> {
  // SABnzbd's route is /sabnzbd/restart, not /sabnzbd/system/restart — the
  // *arr shape does not apply to it, and building the *arr path meant the
  // Restart button answered "Not Found" and restarted nothing.
  const path =
    serviceType === "emby" || serviceType === "jellyfin"
      ? `/api/instances/${instanceId}/media/system/restart`
      : serviceType === "sabnzbd"
        ? `/api/instances/${instanceId}/sabnzbd/restart`
        : `/api/instances/${instanceId}/${serviceType}/system/restart`;
  try {
    await apiFetch(path, { method: "POST" });
  } catch (error) {
    return toResult(error);
  }
  return { ok: true, message: "Restart requested." };
}
