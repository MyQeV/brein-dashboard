"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiFetch, isRedirectError } from "@/lib/api";

export type SaveResult = { ok: true } | { ok: false; errors: string[] };

export async function saveSettings(values: Record<string, string>): Promise<SaveResult> {
  try {
    const response = await apiFetch<{ ok: boolean; errors: string[] }>(
      "/api/settings/system",
      {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(values),
      },
    );
    if (!response.ok) return { ok: false, errors: response.errors };
  } catch (error) {
    if (isRedirectError(error)) throw error;
    return {
      ok: false,
      errors: [
        error instanceof ApiError
          ? error.message
          : "Something went wrong. Please try again.",
      ],
    };
  }
  revalidatePath("/settings/config");
  return { ok: true };
}
