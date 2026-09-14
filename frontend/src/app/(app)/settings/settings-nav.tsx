"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
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

  return (
    <nav aria-label="Settings" className="flex gap-1 border-b border-border">
      {TABS.map((tab) => {
        const active = pathname.startsWith(tab.href);
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
