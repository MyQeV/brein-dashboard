"use client";

import { useRouter } from "next/navigation";

export function TablePicker({ tables, current }: { tables: string[]; current: string }) {
  const router = useRouter();

  return (
    <label className="flex w-fit flex-col gap-1 text-sm">
      Table
      <select
        value={current}
        onChange={(event) => {
          // Reset paging and sorting: page 4 of one table is meaningless in
          // another, and a column that existed there may not exist here.
          router.push(
            `/settings/database?table=${encodeURIComponent(event.target.value)}`,
          );
        }}
        className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
      >
        {tables.map((table) => (
          <option key={table} value={table}>
            {table}
          </option>
        ))}
      </select>
    </label>
  );
}
