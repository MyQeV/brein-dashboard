import Link from "next/link";
import { buttonClasses } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export function Pagination({
  basePath,
  query,
  page,
  pageSize,
  total,
}: {
  basePath: string;
  query: Record<string, string | number | undefined>;
  page: number;
  pageSize: number;
  total: number;
}) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  if (lastPage <= 1) return null;

  function href(target: number): string {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    params.set("page", String(target));
    return `${basePath}?${params.toString()}`;
  }

  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between gap-4 py-2 text-sm"
    >
      <span className="text-muted">
        {first}–{last} of {total}
      </span>
      <span className="flex gap-2">
        <Link
          href={href(page - 1)}
          aria-disabled={page <= 1}
          tabIndex={page <= 1 ? -1 : undefined}
          className={cn(
            buttonClasses("secondary", "sm"),
            page <= 1 && "pointer-events-none opacity-50",
          )}
        >
          Previous
        </Link>
        <Link
          href={href(page + 1)}
          aria-disabled={page >= lastPage}
          tabIndex={page >= lastPage ? -1 : undefined}
          className={cn(
            buttonClasses("secondary", "sm"),
            page >= lastPage && "pointer-events-none opacity-50",
          )}
        >
          Next
        </Link>
      </span>
    </nav>
  );
}
