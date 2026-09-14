import localFont from "next/font/local";

/**
 * Self-hosted through next/font so the CSS variable is set at build time with
 * no extra request.
 */

/**
 * The redesign's face. One variable file covers 200–800, so headings and
 * tabular numbers come from the same axis instead of four static cuts.
 */
export const bricolage = localFont({
  src: [
    {
      path: "./fonts/bricolage-grotesque-latin-wght-normal.woff2",
      weight: "200 800",
      style: "normal",
    },
  ],
  variable: "--font-bricolage",
  display: "swap",
  fallback: ["Helvetica Neue", "Arial", "sans-serif"],
});

export const plexMono = localFont({
  src: [
    {
      path: "./fonts/ibm-plex-mono-latin-400-normal.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/ibm-plex-mono-latin-600-normal.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-plex-mono",
  display: "swap",
  fallback: ["ui-monospace", "monospace"],
});
