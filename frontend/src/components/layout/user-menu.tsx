"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { clientFetch } from "@/lib/client-fetch";
import { cn } from "@/lib/cn";
import type { User } from "@/lib/types";

const ITEM_CLASS =
  "flex w-full items-center rounded-md px-2 py-1.5 text-left text-sm text-muted hover:bg-bg hover:text-text focus-visible:bg-bg focus-visible:text-text";

/**
 * The header's account menu: the username opens Profile and Sign out.
 * Keyboard handling mirrors the theme picker so the two menus behave alike.
 */
export function UserMenu({ user }: { user: User | null }) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLAnchorElement | HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (open) itemRefs.current[0]?.focus();
  }, [open]);

  function onMenuKeyDown(event: React.KeyboardEvent) {
    const items = itemRefs.current.filter((item) => item !== null);
    const count = items.length;
    const current = items.indexOf(document.activeElement as (typeof items)[number]);
    let next: number | null = null;
    if (event.key === "ArrowDown") next = (current + 1) % count;
    else if (event.key === "ArrowUp") next = (current - 1 + count) % count;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    if (next === null) return;
    event.preventDefault();
    items[next]?.focus();
  }

  async function signOut() {
    setSigningOut(true);
    setError(null);
    try {
      // The API blacklists the access token, revokes the refresh token and
      // clears both cookies. A 401 here means the session was already gone,
      // and clientFetch's own sign-out lands on the same page.
      await clientFetch<void>("/logout", { method: "POST" });
    } catch (caught) {
      setSigningOut(false);
      setError(caught instanceof Error ? caught.message : "Could not sign out");
      return;
    }
    // A full navigation, not the router: it drops the now-playing socket and
    // every cached response the old session built up.
    window.location.href = "/login";
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "flex items-center gap-1 rounded-md px-2 py-1.5 text-sm text-muted hover:text-text",
          open && "text-text",
        )}
      >
        <span className="max-w-40 truncate">{user?.username ?? "—"}</span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className={cn("shrink-0 transition-transform", open && "rotate-180")}
        >
          <path d="M3 4.5l3 3 3-3" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 z-(--z-dropdown) mt-2 w-44 rounded-lg border border-border bg-surface p-1 shadow-(--shadow-elevated)"
        >
          <Link
            ref={(element) => {
              itemRefs.current[0] = element;
            }}
            href="/profile"
            role="menuitem"
            tabIndex={0}
            onClick={() => setOpen(false)}
            className={ITEM_CLASS}
          >
            Profile
          </Link>
          <button
            ref={(element) => {
              itemRefs.current[1] = element;
            }}
            type="button"
            role="menuitem"
            tabIndex={-1}
            disabled={signingOut}
            onClick={() => void signOut()}
            className={cn(ITEM_CLASS, "disabled:opacity-60")}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
          {error && (
            <p role="alert" className="px-2 py-1.5 text-xs text-error">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
