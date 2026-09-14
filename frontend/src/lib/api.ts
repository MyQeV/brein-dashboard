import { cookies } from "next/headers";
import { redirect } from "next/navigation";

/** Server-side API access. Browser code must use `clientFetch` instead. */

const API_ORIGIN = process.env.BREIN_API_ORIGIN ?? "http://localhost:8001";

const CSRF_COOKIE = "brein_csrf";
const CSRF_HEADER = "X-CSRF-Token";

/**
 * True for the sentinel `redirect()` throws. Catching it and reporting it as
 * a failure turns an intended navigation into a generic error message.
 */
export function isRedirectError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "digest" in error &&
    typeof (error as { digest: unknown }).digest === "string" &&
    (error as { digest: string }).digest.startsWith("NEXT_REDIRECT")
  );
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function detailOf(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    // Non-JSON error body; fall through to the status text.
  }
  return response.statusText || `HTTP ${response.status}`;
}

/**
 * Fetch from the API in a server component or server action.
 *
 * NOTE: on 401 this calls `redirect()`, which works by throwing. A caller
 * that wraps this in try/catch must re-throw that control-flow error —
 * `isRedirectError` below exists for exactly that.
 *
 * Forwards the caller's cookies, so the request carries the same session the
 * browser has. A 401 means the session is genuinely gone by the time the
 * server renders, so it redirects to login rather than throwing into an
 * error boundary.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit & { allowUnauthenticated?: boolean } = {},
): Promise<T> {
  const { allowUnauthenticated, ...requestInit } = init;
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();

  // The API challenges cookie-authenticated writes. Echo the double-submit
  // token so server actions are not refused; the API issues the cookie to any
  // authenticated caller, so it is present by the time a write happens.
  const method = (requestInit.method ?? "GET").toUpperCase();
  const csrfToken =
    method === "GET" || method === "HEAD"
      ? undefined
      : cookieStore.get(CSRF_COOKIE)?.value;

  const response = await fetch(`${API_ORIGIN}${path}`, {
    ...requestInit,
    headers: {
      ...requestInit.headers,
      ...(cookieHeader ? { cookie: cookieHeader } : {}),
      ...(csrfToken ? { [CSRF_HEADER]: csrfToken } : {}),
    },
    // Dashboards are live data; a cached read would show stale playback.
    cache: "no-store",
  });

  if (response.status === 401 && !allowUnauthenticated) {
    redirect("/login");
  }
  if (!response.ok) {
    throw new ApiError(await detailOf(response), response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type SoftResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

/**
 * For statuses that are an expected answer rather than a fault, so the page
 * can say so server-side.
 *
 * Two cases matter here: 403, because several instance tabs are admin-only,
 * and 502, because an instance can point at a service that is switched off or
 * unreachable — which is normal, not a crash. Throwing either into the error
 * boundary is wrong twice over: it loses the surrounding chrome, and
 * error.tsx only renders after hydration, so the served HTML is a blank page.
 */
const SOFT_STATUSES = new Set([401, 403, 502, 503, 504]);

export async function softApiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<SoftResult<T>> {
  try {
    return { ok: true, data: await apiFetch<T>(path, init) };
  } catch (error) {
    if (error instanceof ApiError && SOFT_STATUSES.has(error.status)) {
      return { ok: false, status: error.status, message: error.message };
    }
    throw error;
  }
}
