"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useNowPlayingContext } from "@/lib/now-playing-context";
import { CATEGORY_LABELS, CATEGORY_ORDER, serviceIcon } from "@/lib/service-types";
import { useServiceTypes } from "@/lib/service-types-context";
import type { Instance } from "@/lib/types";

const PRIMARY_LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/now-playing", label: "Now playing" },
  { href: "/calendar", label: "Calendar" },
];

/** The stream count the old nav carried beside "Now playing". */
function NowPlayingCount() {
  const { sessions } = useNowPlayingContext();
  if (sessions.length === 0) return null;
  return (
    <span
      role="img"
      aria-label={`${sessions.length} playing`}
      className="ml-auto rounded-full bg-accent/15 px-1.5 text-xs font-medium tabular-nums text-accent"
    >
      {sessions.length}
      <span className="sr-only"> playing</span>
    </span>
  );
}

function NavLink({
  href,
  label,
  active,
  icon,
  badge,
}: {
  href: string;
  label: string;
  active: boolean;
  icon?: string;
  badge?: ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-md px-2 py-2 text-sm lg:py-1.5",
        active ? "bg-surface text-text" : "text-muted hover:text-text hover:bg-surface",
      )}
    >
      {icon ? (
        // biome-ignore lint/performance/noImgElement: fixed-size SVG from FastAPI /static, nothing to optimize
        <img src={icon} alt="" aria-hidden="true" className="size-4 shrink-0" />
      ) : (
        <span aria-hidden="true" className="size-4 shrink-0" />
      )}
      <span className="truncate">{label}</span>
      {badge}
    </Link>
  );
}

export function Sidebar({
  instances,
  className,
}: {
  instances: Instance[];
  className?: string;
}) {
  // Read here, not from a header in the layout: layouts are not re-rendered
  // on soft navigation between sibling pages, so a path threaded down from
  // the server goes stale and the active link sticks to the first page shown.
  const currentPath = usePathname();
  const types = useServiceTypes();
  const configured = instances.filter((i) => i.is_configured && i.active !== false);

  return (
    <aside
      className={cn(
        "flex w-56 shrink-0 flex-col gap-4 border-r border-border bg-bg p-3",
        className,
      )}
    >
      <Link href="/" className="flex items-center gap-2 px-2 py-1 font-semibold">
        {/* biome-ignore lint/performance/noImgElement: static SVG logo */}
        <img src="/static/icons/brein.svg" alt="" aria-hidden="true" className="size-5" />
        Brein
      </Link>

      <nav aria-label="Main" className="flex flex-col gap-4">
        <div className="flex flex-col gap-0.5">
          {PRIMARY_LINKS.map((link) => (
            <NavLink
              key={link.href}
              href={link.href}
              label={link.label}
              active={
                link.href === "/"
                  ? currentPath === "/" || currentPath.startsWith("/dashboard")
                  : currentPath.startsWith(link.href)
              }
              badge={link.href === "/now-playing" ? <NowPlayingCount /> : undefined}
            />
          ))}
        </div>

        {CATEGORY_ORDER.map((category) => {
          const group = configured.filter((i) => i.category === category);
          if (group.length === 0) return null;
          return (
            <div key={category} className="flex flex-col gap-0.5">
              <span className="px-2 text-xs font-medium uppercase tracking-wide text-muted">
                {CATEGORY_LABELS[category] ?? category}
              </span>
              {group.map((instance) => (
                <NavLink
                  key={instance.id}
                  href={`/instance/${instance.id}`}
                  label={instance.label ?? String(instance.id)}
                  active={currentPath.startsWith(`/instance/${instance.id}`)}
                  icon={serviceIcon(types, instance.service_type)}
                />
              ))}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
