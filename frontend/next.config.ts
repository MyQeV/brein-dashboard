import type { NextConfig } from "next";

// The FastAPI app keeps serving the API (and, during the migration, the Jinja
// pages we have not ported yet). Proxying rather than calling it cross-origin
// keeps the auth cookie first-party, which is what makes SameSite=Lax work.
const API_ORIGIN = process.env.BREIN_API_ORIGIN ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the runtime image.
  output: "standalone",
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
