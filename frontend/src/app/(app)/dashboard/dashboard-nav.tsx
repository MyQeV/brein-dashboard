"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";

const TABS = [
  { href: "/dashboard", label: "Watch time" },
  { href: "/dashboard/daily", label: "Daily" },
  { href: "/dashboard/movies", label: "Movies" },
  { href: "/dashboard/series", label: "Series" },
  { href: "/dashboard/library", label: "Library" },
  { href: "/dashboard/downloads", label: "Downloads" },
];

/**
 * The filters the tabs share, carried from one to the next. A bare tab link
 * reopened every tab on its default range, so Watch time → Movies → Daily
 * silently dropped the month the user had picked. Named as the pages read
 * them (`firstParam(searchParams.start_date)` and so on); `days` is left
 * out because the range bar derives the preset from the dates.
 */
const CARRIED_PARAMS = ["start_date", "end_date", "instance_ids", "user_ids"];

export function DashboardNav() {
  const pathname = usePathname();
  const params = useSearchParams();
  const navRef = useRef<HTMLElement | null>(null);

  const carried = new URLSearchParams();
  for (const key of CARRIED_PARAMS) {
    const value = params.get(key);
    if (value) carried.set(key, value);
  }
  const query = carried.toString();
  const suffix = query ? `?${query}` : "";

  // The strip scrolls on phones with its scrollbar hidden; without this the
  // current tab can sit off-screen with no hint that there is more.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run on navigation, not on anything read inside
  useEffect(() => {
    navRef.current
      ?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [pathname]);

  return (
    <nav
      ref={navRef}
      aria-label="Dashboard sections"
      className="-mx-4 flex gap-1 overflow-x-auto overflow-y-hidden whitespace-nowrap px-4 shadow-[inset_0_-1px_0_var(--color-border)] [scrollbar-width:none] lg:mx-0 lg:px-0 [&::-webkit-scrollbar]:hidden lg:overflow-visible"
    >
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={`${tab.href}${suffix}`}
            aria-current={active ? "page" : undefined}
            className={cn(
              "shrink-0 border-b-2 px-3 py-2 text-sm",
              active
                ? "border-accent text-text"
                : "border-transparent text-muted hover:text-text",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
