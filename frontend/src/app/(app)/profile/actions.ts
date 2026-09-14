"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiFetch, isRedirectError } from "@/lib/api";
import type { User } from "@/lib/types";

/**
 * Actions return a result envelope and never throw. A thrown server action
 * surfaces as an error boundary, which loses the form the user was filling in
 * along with everything they typed.
 */
export type ActionResult = { ok: true } | { ok: false; error: string; status?: number };

function toResult(error: unknown): ActionResult {
  // redirect() signals by throwing; swallowing it would strand a signed-out
  // user on the form instead of sending them to login.
  if (isRedirectError(error)) throw error;
  if (error instanceof ApiError) {
    return { ok: false, error: error.message, status: error.status };
  }
  return { ok: false, error: "Something went wrong. Please try again." };
}

export async function saveProfile(input: {
  email: string;
  full_name: string;
}): Promise<ActionResult> {
  try {
    await apiFetch<User>("/users/me", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        email: input.email.trim() || null,
        full_name: input.full_name.trim() || null,
      }),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/profile");
  return { ok: true };
}

export async function changePassword(input: {
  current_password: string;
  new_password: string;
}): Promise<ActionResult> {
  try {
    await apiFetch<void>("/users/me/change-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch (error) {
    return toResult(error);
  }
  return { ok: true };
}
