"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * The dialog shell: portal, backdrop, Escape, and the one width rule.
 *
 * Sized against the viewport rather than a fixed cap — session rows carry
 * four columns, and a 42rem dialog truncated titles on a screen with room
 * to spare.
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
      if (event.key === "Escape") {
        onClose();
        return;
      }
      // Keep Tab inside the dialog. The page behind the backdrop is still in
      // the tab order otherwise, so tabbing past ✕ landed on the nav
      // underneath, which is unreachable by mouse and confusing by keyboard.
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!mounted) return null;

  return createPortal(
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop click closes the modal; the operable elements are inside the dialog
    <div
      // Anchored near the top rather than centred: a centred dialog grows from
      // both edges, so expanding a row jumps the whole thing upwards. This way
      // the top edge holds still and the content only grows downwards.
      className="fixed inset-0 z-600 flex items-start justify-center overflow-y-auto bg-(--scrim) p-4 pt-[7vh]"
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
        className="flex max-h-[85vh] w-full max-w-[min(72rem,92vw)] flex-col rounded-lg border border-border bg-surface shadow-(--shadow-elevated)"
      >
        <header className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
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
            className="rounded-sm p-1 text-muted hover:bg-surface-2 hover:text-text"
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

        <div className="overflow-y-auto p-5">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
