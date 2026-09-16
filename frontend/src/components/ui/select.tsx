import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";
import { CONTROL_HEIGHT } from "./control";

type Size = "sm" | "md";

const SIZES: Record<Size, string> = {
  sm: `${CONTROL_HEIGHT.sm} px-2`,
  md: `${CONTROL_HEIGHT.md} px-3`,
};

/**
 * `size` is the control height, as on Button. The native attribute of the
 * same name (visible rows of a listbox) is not passed through; nothing here
 * renders a listbox.
 */
type Props = Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> & { size?: Size };

/** The one styled `<select>`; a Field-height control by default, `sm` beside small buttons. */
export function Select({ size = "md", className, ...props }: Props) {
  return (
    <select
      className={cn(
        "rounded-md border border-border bg-bg text-sm",
        SIZES[size],
        className,
      )}
      {...props}
    />
  );
}
