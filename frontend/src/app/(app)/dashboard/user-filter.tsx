"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

/**
 * Multi-select, mirroring the old chip filter: chosen users show as removable
 * chips, and the dropdown toggles membership.
 *
 * `user.id` must be the compound "instance_id:user_id" key the backend
 * expects (see `_user_instance_filter` in brein/store/metrics_helpers.py) —
 * a bare user_id is silently dropped by the API's filter, not applied.
 */
export function UserFilter({ users }: { users: { id: string; name: string }[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();

  // Dismissed the way the theme picker is: without this the list stayed open
  // over the page once you clicked anything else, and Escape did nothing.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const selected = (params.get("user_ids") ?? "")
    .split(",")
    .filter((value) => value !== "");

  function commit(ids: string[]) {
    const query = new URLSearchParams(params.toString());
    if (ids.length === 0) query.delete("user_ids");
    else query.set("user_ids", ids.join(","));
    router.push(`${pathname}?${query.toString()}`);
  }

  function toggle(id: string) {
    commit(
      selected.includes(id)
        ? selected.filter((value) => value !== id)
        : [...selected, id],
    );
  }

  if (users.length === 0) return null;

  return (
    <div ref={containerRef} className="relative flex flex-wrap items-center gap-1">
      {selected.map((id) => {
        const user = users.find((candidate) => candidate.id === id);
        return (
          <span
            key={id}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 text-xs"
          >
            {user?.name ?? id}
            <button
              type="button"
              aria-label={`Remove ${user?.name ?? id}`}
              onClick={() => toggle(id)}
              className="text-muted hover:text-text"
            >
              ✕
            </button>
          </span>
        );
      })}

      <Button
        size="sm"
        variant="secondary"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        Users
      </Button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Filter by user"
          className="absolute top-full right-0 z-(--z-dropdown) mt-1 max-h-64 w-56 overflow-y-auto rounded-md border border-border bg-surface p-1"
        >
          {users.map((user) => (
            <div key={user.id}>
              {/* A checkbox nested in a button is interactive content inside
                  a button: two controls announced, and the state on neither.
                  One button carrying aria-checked, with the tick drawn. */}
              <button
                type="button"
                role="menuitemcheckbox"
                aria-checked={selected.includes(user.id)}
                onClick={() => toggle(user.id)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-border/30"
              >
                <span
                  aria-hidden="true"
                  className="inline-flex size-4 shrink-0 items-center justify-center rounded-[3px] border border-border text-[10px] leading-none"
                >
                  {selected.includes(user.id) ? "✓" : ""}
                </span>
                <span className="truncate">{user.name}</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
