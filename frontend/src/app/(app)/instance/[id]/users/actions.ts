"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiFetch, isRedirectError } from "@/lib/api";

export type ActionResult = { ok: true } | { ok: false; error: string };

function toResult(error: unknown): ActionResult {
  if (isRedirectError(error)) throw error;
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

/** The fields the API's PATCH accepts that the user list can seed. */
export type UserEdit = {
  name?: string;
  new_password?: string;
  is_administrator?: boolean;
  is_disabled?: boolean;
  enable_live_tv?: boolean;
  max_simultaneous_streams?: number;
  enable_all_folders?: boolean;
  enabled_folder_ids?: string[];
};

/**
 * Update one Emby or Jellyfin user.
 *
 * Only changed fields are sent: the API treats a null as "leave alone" and
 * applies name, password and policy through three separate upstream calls, so
 * sending the whole form would rewrite the password on every save.
 */
export async function updateMediaUser(
  instanceId: number,
  userId: string,
  changes: UserEdit,
): Promise<ActionResult> {
  if (Object.keys(changes).length === 0) return { ok: true };
  try {
    await apiFetch(`/api/instances/${instanceId}/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(changes),
    });
  } catch (error) {
    return toResult(error);
  }
  revalidatePath(`/instance/${instanceId}/users`);
  return { ok: true };
}
