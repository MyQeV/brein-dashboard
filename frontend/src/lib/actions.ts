import { ApiError, isRedirectError } from "@/lib/api";

/**
 * Actions return a result envelope and never throw. A thrown server action
 * surfaces as an error boundary, which loses the form the user was filling in
 * along with everything they typed.
 */
export type ActionResult = { ok: true; message?: string } | { ok: false; error: string };

export function toResult(error: unknown): ActionResult {
  // redirect() signals by throwing; swallowing it would strand a signed-out
  // user on the form instead of sending them to login.
  if (isRedirectError(error)) throw error;
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}
