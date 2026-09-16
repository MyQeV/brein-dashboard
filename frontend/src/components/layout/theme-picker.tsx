"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { setPreference } from "@/lib/preferences";
import {
  isTheme,
  THEME_LABELS,
  THEME_STORAGE_KEY,
  THEME_SWATCHES,
  THEMES,
  type Theme,
} from "@/lib/theme";

export function ThemePicker() {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<Theme>("dark");
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const current = document.documentElement.getAttribute("data-theme");
    if (isTheme(current)) setActive(current);
  }, []);

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

  // A menu is expected to take the arrow keys: focus lands on the current
  // theme when it opens, Up/Down step through with wrap-around, Home and
  // End jump to the ends. Without this, `role="menu"` was a promise the
  // buttons did not keep.
  useEffect(() => {
    if (open) itemRefs.current[THEMES.indexOf(active)]?.focus();
  }, [open, active]);

  function onMenuKeyDown(event: React.KeyboardEvent) {
    const count = THEMES.length;
    const current = itemRefs.current.indexOf(
      document.activeElement as HTMLButtonElement | null,
    );
    let next: number | null = null;
    if (event.key === "ArrowDown") next = (current + 1) % count;
    else if (event.key === "ArrowUp") next = (current - 1 + count) % count;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    if (next === null) return;
    event.preventDefault();
    itemRefs.current[next]?.focus();
  }

  function apply(theme: Theme) {
    document.documentElement.setAttribute("data-theme", theme);
    setActive(theme);
    setOpen(false);
    triggerRef.current?.focus();
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Private mode or blocked storage: the server copy below still persists.
    }
    // Best-effort: the theme is already applied locally, so a failed save is
    // not worth interrupting the user for.
    void setPreference("theme", theme).catch(() => undefined);
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-label="Choose theme"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="grid size-9 place-items-center rounded-md border border-border bg-surface text-muted hover:text-text"
      >
        <span
          aria-hidden="true"
          className="size-4 rounded-full border border-border"
          style={{ background: THEME_SWATCHES[active].accent }}
        />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Theme options"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 z-(--z-dropdown) mt-2 w-44 rounded-lg border border-border bg-surface p-1 shadow-(--shadow-elevated)"
        >
          {THEMES.map((theme, index) => (
            <button
              key={theme}
              ref={(element) => {
                itemRefs.current[index] = element;
              }}
              type="button"
              role="menuitemradio"
              aria-checked={theme === active}
              // Roving focus: only the focused item is in the tab order, so
              // Tab leaves the menu instead of walking every theme.
              tabIndex={theme === active ? 0 : -1}
              onClick={() => apply(theme)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                theme === active ? "bg-bg text-text" : "text-muted hover:text-text",
              )}
            >
              <span
                aria-hidden="true"
                className="size-4 shrink-0 rounded-full border border-border"
                style={{
                  background: `linear-gradient(135deg, ${THEME_SWATCHES[theme].bg} 50%, ${THEME_SWATCHES[theme].accent} 50%)`,
                }}
              />
              {THEME_LABELS[theme]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
