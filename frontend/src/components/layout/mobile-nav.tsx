"use client";

import { useEffect, useRef, useState } from "react";
import { LG_AND_UP } from "@/lib/breakpoints";
import type { Instance } from "@/lib/types";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { Sidebar } from "./sidebar";

/**
 * The phone shell's navigation: a hamburger in the header that opens the
 * same Sidebar as a drawer. Every server and tool link stays reachable —
 * the drawer is the desktop sidebar, not a shorter copy of it.
 */
export function MobileNav({ instances }: { instances: Instance[] }) {
  const [open, setOpen] = useState(false);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    // Rotating a tablet past lg swaps the drawer for the sidebar; the drawer
    // state must follow, or its listeners keep running behind a hidden panel.
    const mq = window.matchMedia(LG_AND_UP);
    function onChange(event: MediaQueryListEvent) {
      if (event.matches) setOpen(false);
    }
    mq.addEventListener("change", onChange);
    return () => {
      document.removeEventListener("keydown", onKey);
      mq.removeEventListener("change", onChange);
      openerRef.current?.focus();
    };
  }, [open]);

  useFocusTrap(panelRef, open);

  return (
    <>
      <button
        ref={openerRef}
        type="button"
        aria-label="Open navigation"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="grid size-10 place-items-center rounded-md text-muted hover:bg-surface hover:text-text"
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M3 5h14M3 10h14M3 15h14" />
        </svg>
      </button>

      {open && (
        <div className="fixed inset-0 z-(--z-overlay) lg:hidden">
          <div
            aria-hidden="true"
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-(--scrim)"
          />
          <div
            ref={panelRef}
            id="mobile-nav"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            onClickCapture={(event) => {
              if (
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.button !== 0
              ) {
                return;
              }
              if (event.target instanceof Element && event.target.closest("a")) {
                setOpen(false);
              }
            }}
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col overflow-y-auto bg-bg shadow-(--shadow-elevated)"
          >
            <div className="flex justify-end p-2">
              <button
                ref={closeRef}
                type="button"
                aria-label="Close navigation"
                onClick={() => setOpen(false)}
                className="grid size-10 place-items-center rounded-md text-muted hover:bg-surface hover:text-text"
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 20 20"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M5 5l10 10M15 5L5 15" />
                </svg>
              </button>
            </div>
            <Sidebar instances={instances} className="w-full flex-1 border-r-0 pt-0" />
          </div>
        </div>
      )}
    </>
  );
}
