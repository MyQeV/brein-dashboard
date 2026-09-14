"use client";

/** Browser-side API access. Server components must use `apiFetch` instead. */

const CSRF_COOKIE = "brein_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * The API challenges cookie-authenticated writes, and browser calls carry no
 * Authorization header, so every write must echo the double-submit token. The
 * cookie is deliberately readable by JS — that is the mechanism, not a leak.
 */
function csrfToken(): string | undefined {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : undefined;
}

export class ClientApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ClientApiError";
  }
}

/**
 * Outcome of a refresh attempt. The three states must stay distinct:
 *
 *   true  — refreshed; retry the original call.
 *   false — the refresh token was definitively rejected; sign the user out.
 *   null  — transient (offline, 5xx). Callers must NOT redirect to login;
 *           doing so logs people out every time the network hiccups.
 */
type RefreshOutcome = true | false | null;

// One in-flight refresh, shared. Without this, a page that fires six requests
// on mount performs six refreshes, and the rotating refresh token means all
// but one are rejected.
let inFlightRefresh: Promise<RefreshOutcome> | null = null;

async function refreshSession(): Promise<RefreshOutcome> {
  if (inFlightRefresh) return inFlightRefresh;

  inFlightRefresh = (async (): Promise<RefreshOutcome> => {
    try {
      const response = await fetch("/refresh", {
        method: "POST",
        credentials: "include",
      });
      if (response.ok) return true;
      if (response.status === 401 || response.status === 403) return false;
      return null;
    } catch {
      return null;
    } finally {
      inFlightRefresh = null;
    }
  })();

  return inFlightRefresh;
}

function signOut(): void {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `/login?next=${next}`;
}

async function parseError(response: Response): Promise<ClientApiError> {
  let detail: string = response.statusText || `HTTP ${response.status}`;
  let body: unknown;
  try {
    body = await response.json();
    const candidate = (body as { detail?: unknown }).detail;
    if (typeof candidate === "string") detail = candidate;
  } catch {
    // Non-JSON error body; keep the status text.
  }
  return new ClientApiError(detail, response.status, body);
}

/**
 * Fetch from the API in the browser, refreshing the session once on 401.
 */
export async function clientFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const send = () => {
    // Read per attempt: a refresh in between may have rotated the token.
    const token = SAFE_METHODS.has(method) ? undefined : csrfToken();
    return fetch(path, {
      ...init,
      credentials: "include",
      headers: {
        ...init.headers,
        ...(token ? { [CSRF_HEADER]: token } : {}),
      },
    });
  };

  let response = await send();

  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed === true) {
      response = await send();
    } else if (refreshed === false) {
      signOut();
      throw new ClientApiError("Session expired", 401);
    }
    // refreshed === null: transient. Fall through and report the original
    // failure so the caller can show an error instead of a login redirect.
  }

  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
