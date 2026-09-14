import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({
  title,
  actions,
  className,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("rounded-lg bg-surface", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          {title ? <h2 className="text-sm font-semibold">{title}</h2> : <span />}
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
