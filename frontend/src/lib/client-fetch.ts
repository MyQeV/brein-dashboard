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

class ClientApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
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

/**
 * Whether the cookie jar holds a live session after all.
 *
 * The refresh token rotates, and two tabs waking up together both try to
 * spend the same one: the loser's refresh is rejected even though the winner
 * has just put a fresh access cookie in the shared jar. One probe tells the
 * two apart before anyone is signed out.
 */
async function sessionAlive(): Promise<boolean> {
  try {
    const response = await fetch("/users/me", { credentials: "include" });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * To the login page, with the way back. A full navigation rather than the
 * router: it drops every piece of client state the old session built up —
 * the now-playing socket, cached responses — instead of carrying them over.
 */
export function signOut(): void {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `/login?next=${next}`;
}

/**
 * The API's `detail` when it is a plain message. A 422 carries a list of
 * field errors instead, which is not something to render as text.
 */
export async function errorDetail(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : undefined;
  } catch {
    // Non-JSON error body.
    return undefined;
  }
}

async function parseError(response: Response): Promise<ClientApiError> {
  const detail = await errorDetail(response);
  return new ClientApiError(
    detail ?? (response.statusText || `HTTP ${response.status}`),
    response.status,
  );
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
    if (refreshed === true || (refreshed === false && (await sessionAlive()))) {
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
