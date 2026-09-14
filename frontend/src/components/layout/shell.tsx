import Link from "next/link";
import type { ReactNode } from "react";
import { NowPlayingProvider } from "@/lib/now-playing-context";
import type { Instance, User } from "@/lib/types";
import { MobileNav } from "./mobile-nav";
import { Sidebar } from "./sidebar";
import { ThemePicker } from "./theme-picker";

export function Shell({
  user,
  instances,
  children,
}: {
  user: User | null;
  instances: Instance[];
  children: ReactNode;
}) {
  return (
    <NowPlayingProvider>
      <div className="flex h-full">
        <Sidebar instances={instances} className="max-lg:hidden" />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center justify-between gap-2 border-b border-border px-2 lg:justify-end lg:px-4">
            <div className="flex items-center gap-1 lg:hidden">
              <MobileNav instances={instances} />
              <Link href="/" className="flex items-center gap-2 px-1 font-semibold">
                {/* biome-ignore lint/performance/noImgElement: static SVG logo */}
                <img
                  src="/static/icons/brein.svg"
                  alt=""
                  aria-hidden="true"
                  className="size-5"
                />
                Brein
              </Link>
            </div>
            <div className="flex items-center gap-2">
              {user?.is_admin && (
                <Link
                  href="/settings"
                  className="rounded-md px-2 py-1.5 text-sm text-muted hover:text-text"
                >
                  Settings
                </Link>
              )}
              <ThemePicker />
              <Link
                href="/profile"
                className="rounded-md px-2 py-1.5 text-sm text-muted hover:text-text"
              >
                {user?.username ?? "—"}
              </Link>
            </div>
          </header>
          <main className="min-w-0 flex-1 overflow-auto p-4 lg:p-6">{children}</main>
        </div>
      </div>
    </NowPlayingProvider>
  );
}
