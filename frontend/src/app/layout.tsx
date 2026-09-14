/*
 * Copyright (C) 2026 MyQeV
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
 * General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import type { Metadata } from "next";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import { bricolage, plexMono } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Brein", template: "%s · Brein" },
  description: "Centralized dashboard and management hub for your media stack.",
  icons: { icon: "/static/icons/brein.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`h-full ${bricolage.variable} ${plexMono.variable}`}
      // The inline script below rewrites this before hydration; without
      // suppression React would warn about the mismatch it causes on purpose.
      data-theme="dark"
      suppressHydrationWarning
    >
      <head>
        {/* Applies the stored theme before first paint. Without this the page
            renders in the default theme and then swaps, which is visible. */}
        <script
          // biome-ignore lint/security/noDangerouslySetInnerHtml: fixed string, no interpolation
          dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }}
        />
      </head>
      <body className="h-full">{children}</body>
    </html>
  );
}
