"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "@/lib/use-focus-trap";

/**
 * The dialog shell: portal, backdrop, Escape, and the one width rule.
 *
 * Sized against the viewport rather than a fixed cap — session rows carry
 * four columns, and a 42rem dialog truncated titles on a screen with room
 * to spare. Below lg it is a full-screen sheet instead: a floating card on
 * a phone left a sliver of page around it, wasted the width the tables
 * need, and put the close button under a thumb's reach only by luck.
 */
export function Modal({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => setMounted(true), []);

  // Remember whoever opened this and give the focus back on close. Without
  // it, closing a dialog opened from a table row left focus on <body>, so the
  // next Tab started again from the top of the page.
  useEffect(() => {
    const opener = document.activeElement;
    return () => {
      if (opener instanceof HTMLElement && document.contains(opener)) {
        opener.focus();
      }
    };
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Keep Tab inside the dialog. The page behind the backdrop is still in the
  // tab order otherwise, so tabbing past ✕ landed on the nav underneath,
  // which is unreachable by mouse and confusing by keyboard.
  useFocusTrap(dialogRef, true);

  if (!mounted) return null;

  return createPortal(
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop click closes the modal; the operable elements are inside the dialog
    <div
      // Anchored near the top rather than centred: a centred dialog grows from
      // both edges, so expanding a row jumps the whole thing upwards. This way
      // the top edge holds still and the content only grows downwards.
      className="fixed inset-0 z-(--z-modal) flex items-start justify-center overflow-y-auto bg-(--scrim) lg:p-4 lg:pt-[7dvh]"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="flex h-dvh w-full flex-col bg-surface lg:h-auto lg:max-h-[85dvh] lg:max-w-[min(72rem,92vw)] lg:rounded-lg lg:border lg:border-border lg:shadow-(--shadow-elevated)"
      >
        <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3 lg:px-5 lg:py-4">
          <div className="flex min-w-0 flex-col gap-0.5">
            <h2 className="truncate text-base font-semibold">{title}</h2>
            {subtitle && <p className="truncate text-xs text-muted">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            // biome-ignore lint/a11y/noAutofocus: focus must move into the dialog on open
            autoFocus
            // 44px on touch widths, the compact desktop size from lg up.
            className="-m-2 rounded-sm p-3 text-muted hover:bg-surface-2 hover:text-text lg:m-0 lg:p-1"
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
        </header>

        <div className="overflow-y-auto p-4 pb-[max(1rem,env(safe-area-inset-bottom))] lg:p-5">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
