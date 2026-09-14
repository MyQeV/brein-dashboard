"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { tabsFor } from "@/lib/service-types";
import { useServiceTypes } from "@/lib/service-types-context";

export function InstanceTabs({
  instanceId,
  serviceType,
  isAdmin,
}: {
  instanceId: number;
  serviceType: string;
  isAdmin: boolean;
}) {
  const pathname = usePathname();
  const types = useServiceTypes();
  const tabs = tabsFor(types, serviceType, isAdmin);
  // Settings exposes the target's system info and host config, so it is
  // admin-only — matching the gate on the API.
  const all = isAdmin ? [...tabs, { slug: "settings", label: "Settings" }] : tabs;

  if (all.length === 0) return null;

  return (
    <nav
      aria-label="Instance sections"
      className="flex flex-wrap gap-1 border-b border-border"
    >
      {all.map((tab) => {
        const href = `/instance/${instanceId}/${tab.slug}`;
        const active = pathname === href;
        return (
          <Link
            key={tab.slug}
            href={href}
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
