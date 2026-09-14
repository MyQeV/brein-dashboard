import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";
import { CONTROL_HEIGHT } from "./control";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:opacity-90 border-transparent",
  secondary: "bg-surface text-text hover:border-accent",
  ghost: "bg-transparent text-muted hover:text-text hover:bg-surface border-transparent",
  danger: "bg-error text-white hover:opacity-90 border-transparent",
};

const SIZES: Record<Size, string> = {
  sm: `${CONTROL_HEIGHT.sm} px-3 text-sm`,
  md: `${CONTROL_HEIGHT.md} px-4 text-sm`,
};

/**
 * Note for anyone reaching for shadcn conventions: there is no `asChild`
 * here. Render a `<Link className={buttonClasses(...)}>` for link-buttons.
 */
export function buttonClasses(variant: Variant = "primary", size: Size = "md"): string {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-md border border-border",
    "font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none",
    VARIANTS[variant],
    SIZES[size],
  );
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
};

export function Button({ variant, size, className, type, ...props }: Props) {
  return (
    <button
      // Buttons inside a <form> default to submit, which fires the form when
      // you meant to open a dialog.
      type={type ?? "button"}
      className={cn(buttonClasses(variant, size), className)}
      {...props}
    />
  );
}
