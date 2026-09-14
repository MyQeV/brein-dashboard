"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiFetch, isRedirectError } from "@/lib/api";

export type ActionResult = { ok: true } | { ok: false; error: string };

function toResult(error: unknown): ActionResult {
  if (isRedirectError(error)) throw error;
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

export async function updateUserRole(
  userId: string,
  input: { role: string; disabled: boolean },
): Promise<ActionResult> {
  try {
    await apiFetch(`/api/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/users");
  return { ok: true };
}

export async function createUser(input: {
  username: string;
  password: string;
  email: string;
  full_name: string;
  role: string;
}): Promise<ActionResult> {
  try {
    await apiFetch("/api/users", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        username: input.username.trim(),
        password: input.password,
        email: input.email.trim() || null,
        full_name: input.full_name.trim() || null,
        role: input.role,
      }),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath("/settings/users");
  return { ok: true };
}
