"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiFetch, isRedirectError } from "@/lib/api";

export type ActionResult =
  | { ok: true; id?: number }
  | { ok: false; error: string; status?: number };

function toResult(error: unknown): ActionResult {
  if (isRedirectError(error)) throw error;
  if (error instanceof ApiError) {
    return { ok: false, error: error.message, status: error.status };
  }
  return { ok: false, error: "Something went wrong. Please try again." };
}

export async function addInstance(serviceType: string): Promise<ActionResult> {
  let created: { id: number };
  try {
    created = await apiFetch<{ id: number; ok: boolean }>("/api/instances", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ service_type: serviceType }),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/app");
  return { ok: true, id: created.id };
}

export async function saveInstance(
  id: number,
  input: {
    label: string;
    host: string;
    port: string;
    api_key: string;
    external_url: string;
    sort_order: string;
    active: boolean;
  },
): Promise<ActionResult> {
  const port = input.port.trim();
  const sortOrder = input.sort_order.trim();

  // Validate here so the user sees the problem beside the field; the API is
  // still the authority.
  if (port && !/^\d+$/.test(port)) {
    return { ok: false, error: "Port must be a whole number." };
  }
  if (port && (Number(port) < 1 || Number(port) > 65535)) {
    return { ok: false, error: "Port must be between 1 and 65535." };
  }
  if (sortOrder && !/^\d+$/.test(sortOrder)) {
    return { ok: false, error: "Order must be a whole number." };
  }

  try {
    await apiFetch(`/api/instances/${id}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        label: input.label.trim() || null,
        host: input.host.trim(),
        port: port ? Number(port) : null,
        // null means "keep the stored key". The form never receives the real
        // one, only a mask, so an untouched field must not overwrite it.
        api_key: input.api_key ? input.api_key : null,
        external_url: input.external_url.trim(),
        active: input.active,
        sort_order: sortOrder ? Number(sortOrder) : null,
      }),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/app");
  revalidatePath(`/settings/app/${id}`);
  return { ok: true };
}

export async function testInstance(
  id: number,
): Promise<{ ok: boolean; message: string }> {
  try {
    return await apiFetch<{ ok: boolean; message: string }>(`/api/instances/${id}/test`, {
      method: "POST",
    });
  } catch (error) {
    if (isRedirectError(error)) throw error;
    return {
      ok: false,
      message: error instanceof ApiError ? error.message : "Connection test failed",
    };
  }
}

export async function deleteInstance(id: number): Promise<ActionResult> {
  try {
    await apiFetch(`/api/instances/${id}`, { method: "DELETE" });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/app");
  return { ok: true };
}
