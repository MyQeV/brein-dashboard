"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";

/**
 * Defined once. The Jinja version of this nav was copy-pasted verbatim into
 * seven templates, so adding a tab meant editing seven files.
 */
const TABS = [
  { href: "/settings/app", label: "App" },
  { href: "/settings/users", label: "Users" },
  { href: "/settings/database", label: "Database" },
  { href: "/settings/tasks", label: "Tasks" },
  { href: "/settings/config", label: "Config" },
  { href: "/settings/logs", label: "Logs" },
];

export function SettingsNav() {
  const pathname = usePathname();
  const navRef = useRef<HTMLElement | null>(null);

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
      aria-label="Settings"
      className="-mx-4 flex gap-1 overflow-x-auto overflow-y-hidden whitespace-nowrap px-4 shadow-[inset_0_-1px_0_var(--color-border)] [scrollbar-width:none] lg:mx-0 lg:px-0 [&::-webkit-scrollbar]:hidden lg:overflow-visible"
    >
      {TABS.map((tab) => {
        const active = pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
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
