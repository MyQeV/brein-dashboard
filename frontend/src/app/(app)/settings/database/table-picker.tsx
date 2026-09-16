"use client";

import { useRouter } from "next/navigation";
import { Select } from "@/components/ui/select";

export function TablePicker({ tables, current }: { tables: string[]; current: string }) {
  const router = useRouter();

  return (
    <label htmlFor="database-table" className="flex w-fit flex-col gap-1 text-sm">
      Table
      <Select
        id="database-table"
        size="sm"
        value={current}
        onChange={(event) => {
          // Reset paging and sorting: page 4 of one table is meaningless in
          // another, and a column that existed there may not exist here.
          router.push(
            `/settings/database?table=${encodeURIComponent(event.target.value)}`,
          );
        }}
      >
        {tables.map((table) => (
          <option key={table} value={table}>
            {table}
          </option>
        ))}
      </Select>
    </label>
  );
}
