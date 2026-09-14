import type { InputHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { CONTROL_HEIGHT } from "./control";

type Props = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  help?: ReactNode;
  error?: string;
};

export function Field({ label, help, error, id, className, ...props }: Props) {
  const inputId = id ?? props.name;
  const helpId = help ? `${inputId}-help` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={inputId} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={inputId}
        aria-describedby={cn(helpId, errorId) || undefined}
        aria-invalid={error ? true : undefined}
        className={cn(
          CONTROL_HEIGHT.md,
          "rounded-md border border-border bg-bg px-3 text-sm",
          "placeholder:text-muted focus:border-accent",
          error && "border-error",
          className,
        )}
        {...props}
      />
      {help && (
        <span id={helpId} className="text-xs text-muted">
          {help}
        </span>
      )}
      {error && (
        <span id={errorId} className="text-xs text-error">
          {error}
        </span>
      )}
    </div>
  );
}

export function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm font-medium">{label}</span>
      <span className="text-sm text-muted">{value}</span>
    </div>
  );
}
