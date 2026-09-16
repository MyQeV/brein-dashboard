"use server";

import { revalidatePath } from "next/cache";
import { type ActionResult, toResult } from "@/lib/actions";
import { apiFetch } from "@/lib/api";

export async function setTaskEnabled(
  taskId: number,
  enabled: boolean,
): Promise<ActionResult> {
  try {
    await apiFetch(`/api/tasks/${taskId}/enabled`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/tasks");
  return { ok: true };
}

export async function setTaskInterval(
  taskId: number,
  intervalSeconds: number,
): Promise<ActionResult> {
  try {
    await apiFetch(`/api/tasks/${taskId}/interval`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ interval_seconds: intervalSeconds }),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/tasks");
  return { ok: true };
}

export async function runTaskNow(taskId: number): Promise<ActionResult> {
  try {
    await apiFetch(`/api/tasks/${taskId}/run`, { method: "POST" });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/tasks");
  return { ok: true };
}
