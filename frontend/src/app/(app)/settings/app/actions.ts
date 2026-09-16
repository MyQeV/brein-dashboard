"use server";

import { revalidatePath } from "next/cache";
import { type ActionResult, toResult } from "@/lib/actions";
import { ApiError, apiFetch, isRedirectError } from "@/lib/api";

export type InstanceInput = {
  label: string;
  host: string;
  port: string;
  api_key: string;
  external_url: string;
  sort_order: string;
  active: boolean;
};

/** The field checks the form shows beside the field; the API is still the authority. */
function invalid(input: InstanceInput): string | null {
  const port = input.port.trim();
  const sortOrder = input.sort_order.trim();
  if (port && !/^\d+$/.test(port)) return "Port must be a whole number.";
  if (port && (Number(port) < 1 || Number(port) > 65535)) {
    return "Port must be between 1 and 65535.";
  }
  if (sortOrder && !/^\d+$/.test(sortOrder)) return "Order must be a whole number.";
  return null;
}

/**
 * Try a connection that is not stored yet. The add form only enables Save
 * once this has passed for the values it is about to send.
 */
export async function testConnection(input: {
  service_type: string;
  host: string;
  port: string;
  api_key: string;
}): Promise<{ ok: boolean; message: string }> {
  const port = input.port.trim();
  try {
    return await apiFetch<{ ok: boolean; message: string }>("/api/instances/test", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        service_type: input.service_type,
        host: input.host.trim(),
        port: port ? Number(port) : null,
        api_key: input.api_key,
      }),
    });
  } catch (error) {
    if (isRedirectError(error)) throw error;
    return {
      ok: false,
      message: error instanceof ApiError ? error.message : "Connection test failed",
    };
  }
}

/** Create an instance from a filled-in form; the API tests the connection before storing it. */
export async function createInstance(
  serviceType: string,
  input: InstanceInput,
): Promise<ActionResult> {
  const problem = invalid(input);
  if (problem) return { ok: false, error: problem };
  const port = input.port.trim();
  const sortOrder = input.sort_order.trim();

  try {
    await apiFetch<{ id: number; ok: boolean }>("/api/instances", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        service_type: serviceType,
        label: input.label.trim() || null,
        host: input.host.trim(),
        port: port ? Number(port) : null,
        api_key: input.api_key,
        external_url: input.external_url.trim(),
        active: input.active,
        sort_order: sortOrder ? Number(sortOrder) : null,
      }),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/app");
  return { ok: true };
}

export async function saveInstance(
  id: number,
  input: InstanceInput,
): Promise<ActionResult> {
  const problem = invalid(input);
  if (problem) return { ok: false, error: problem };
  const port = input.port.trim();
  const sortOrder = input.sort_order.trim();

  try {
    await apiFetch(`/api/instances/${id}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        // The API keeps the stored value on null, so a cleared field has to
        // be sent as what it is: an empty label, no port, the first slot.
        label: input.label.trim(),
        host: input.host.trim(),
        port: port ? Number(port) : null,
        // null means "keep the stored key". The form never receives the real
        // one, only a mask, so an untouched field must not overwrite it.
        api_key: input.api_key ? input.api_key : null,
        external_url: input.external_url.trim(),
        active: input.active,
        sort_order: sortOrder ? Number(sortOrder) : 0,
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
