"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const TABS = [
  { href: "/dashboard", label: "Watch time" },
  { href: "/dashboard/daily", label: "Daily" },
  { href: "/dashboard/movies", label: "Movies" },
  { href: "/dashboard/series", label: "Series" },
  { href: "/dashboard/library", label: "Library" },
  { href: "/dashboard/downloads", label: "Downloads" },
];

export function DashboardNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Dashboard sections" className="flex gap-1 border-b border-border">
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
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
