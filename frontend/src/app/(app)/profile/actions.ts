"use server";

import { revalidatePath } from "next/cache";
import { type ActionResult, toResult } from "@/lib/actions";
import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

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
