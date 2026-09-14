import { type NextRequest, NextResponse } from "next/server";

/** Next 16 renamed `middleware.ts` to `proxy.ts`.
 *
 * This is an optimistic cookie-presence check only. Server Functions are
 * handled as POSTs to the route that uses them rather than as separate
 * routes, so a matcher exclusion also skips proxy coverage — every action
 * and route must still authorize on its own. The API does exactly that. */

const ACCESS_COOKIE = "brein_access_token";
const REFRESH_COOKIE = "brein_refresh_token";

// Screens that must render without a session.
const PUBLIC_PATHS = ["/login", "/setup"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const isPublic = PUBLIC_PATHS.some((path) => pathname.startsWith(path));
  if (isPublic) {
    return NextResponse.next();
  }

  const hasSession =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);

  if (!hasSession) {
    const login = new URL("/login", request.url);
    // Keep the query string: dropping it sends people back to a list page
    // without the filters they had applied.
    login.searchParams.set("next", pathname + search);
    return NextResponse.redirect(login);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Everything except Next internals, the proxied API and static assets.
    // Anchored: bare prefixes would also exclude a future /tokens or
    // /logout-confirm page from the auth check.
    "/((?!_next/static/|_next/image/|api/|ws/|static/|(?:token|refresh|logout|users/me|favicon\\.ico)(?:/|$)).*)",
  ],
};
