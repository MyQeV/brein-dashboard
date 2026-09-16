import { type NextRequest, NextResponse } from "next/server";
import { PATH_HEADER } from "@/lib/api";

/** Next 16 renamed `middleware.ts` to `proxy.ts`.
 *
 * This is an optimistic cookie-presence check only. Server Functions are
 * handled as POSTs to the route that uses them rather than as separate
 * routes, so a matcher exclusion also skips proxy coverage — every action
 * and route must still authorize on its own. The API does exactly that. */

const ACCESS_COOKIE = "brein_access_token";

// Screens that must render without a session.
const PUBLIC_PATHS = ["/login", "/setup"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const isPublic = PUBLIC_PATHS.some((path) => pathname.startsWith(path));
  if (isPublic) {
    return NextResponse.next();
  }

  // The access cookie alone decides. Its max-age is the token's lifetime, so
  // after half an hour idle only the refresh cookie is left — and letting
  // that through meant every server render was refused by the API and
  // bounced to /login with the destination lost. The login page refreshes
  // the session and comes straight back to `next`, without showing a form.
  if (!request.cookies.has(ACCESS_COOKIE)) {
    const login = new URL("/login", request.url);
    // Keep the query string: dropping it sends people back to a list page
    // without the filters they had applied.
    login.searchParams.set("next", pathname + search);
    return NextResponse.redirect(login);
  }

  // Server components cannot see the URL they render for; carry it so a 401
  // mid-render can send the user back here once they have signed in again.
  // Set, not appended: a client cannot plant one.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(PATH_HEADER, pathname + search);
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: [
    // Everything except Next internals, the proxied API and static assets.
    // Anchored: bare prefixes would also exclude a future /tokens or
    // /logout-confirm page from the auth check.
    "/((?!_next/static/|_next/image/|api/|ws/|static/|(?:token|refresh|logout|users/me|favicon\\.ico)(?:/|$)).*)",
  ],
};
