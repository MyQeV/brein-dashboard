import Link from "next/link";
import type { ReactNode } from "react";
import type { Instance, User } from "@/lib/types";
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
    <div className="flex h-full">
      <Sidebar instances={instances} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-end gap-2 border-b border-border px-4">
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
        </header>
        <main className="min-w-0 flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
