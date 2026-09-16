import type { NextConfig } from "next";

// The FastAPI app keeps serving the API (and, during the migration, the Jinja
// pages we have not ported yet). Proxying rather than calling it cross-origin
// keeps the auth cookie first-party, which is what makes SameSite=Lax work.
const API_ORIGIN = process.env.BREIN_API_ORIGIN ?? "http://localhost:8001";

// What the pages actually load: fonts and styles are self-hosted (next/font,
// Tailwind), images come through the API's own proxy on this origin, and the
// now-playing socket is same-origin. Scripts need 'unsafe-inline' because
// the theme is applied by an inline script in <head> before first paint and
// Next's own hydration payload is inlined too; a nonce would need the proxy
// to mint one per request and thread it into both, which is more machinery
// than this buys. 'unsafe-eval' only in development, for the dev overlay.
const CSP = [
  "default-src 'self'",
  "img-src 'self' data: blob:",
  "style-src 'self' 'unsafe-inline'",
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "production" ? "" : " 'unsafe-eval'"}`,
  "connect-src 'self' ws: wss:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  // Self-contained server bundle for the runtime image.
  output: "standalone",
  async headers() {
    return [
      {
        // The HTML Next serves. The API sets its own on everything proxied
        // below, so those paths are left to it rather than doubled up.
        source: "/((?!api/|ws/|static/|(?:token|refresh|logout|users/me)(?:/|$)).*)",
        headers: [
          { key: "Content-Security-Policy", value: CSP },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/token", destination: `${API_ORIGIN}/token` },
      { source: "/refresh", destination: `${API_ORIGIN}/refresh` },
      { source: "/logout", destination: `${API_ORIGIN}/logout` },
      { source: "/users/me", destination: `${API_ORIGIN}/users/me` },
      { source: "/ws/:path*", destination: `${API_ORIGIN}/ws/:path*` },
      // Icons, fonts and vendored assets still live with the Jinja app.
      { source: "/static/:path*", destination: `${API_ORIGIN}/static/:path*` },
    ];
  },
};

export default nextConfig;
