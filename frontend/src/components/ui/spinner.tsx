import { cn } from "@/lib/cn";

/**
 * Pass a `label` when the spinner stands alone, so screen readers announce
 * it. Omit it when there is already visible text beside it — then the ring is
 * decorative and must be hidden instead of announced twice.
 */
export function Spinner({ label, className }: { label?: string; className?: string }) {
  const ring = (
    <span
      className={cn(
        "inline-block size-4 animate-spin rounded-full",
        "border-2 border-border border-t-accent",
      )}
    />
  );

  if (!label) return <span aria-hidden="true">{ring}</span>;

  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center gap-2 text-sm text-muted", className)}
    >
      {ring}
      {label}
    </span>
  );
}
