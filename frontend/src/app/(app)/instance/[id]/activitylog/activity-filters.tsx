"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type Filters = {
  min_date: string;
  max_date: string;
  user_id: string;
  type: string;
};

export function ActivityFilters({
  basePath,
  types,
  users,
  current,
}: {
  basePath: string;
  types: string[];
  users: { id: string; name: string }[];
  current: Filters;
}) {
  const router = useRouter();
  const [filters, setFilters] = useState<Filters>(current);

  function apply(next: Filters) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value) params.set(key, value);
    }
    const query = params.toString();
    // Filters live in the URL, so a filtered view is shareable and survives
    // a reload.
    router.push(query ? `${basePath}?${query}` : basePath);
  }

  function set<K extends keyof Filters>(key: K, value: string) {
    setFilters((previous) => ({ ...previous, [key]: value }));
  }

  return (
    <Card>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          apply(filters);
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          From
          <input
            type="date"
            value={filters.min_date}
            onChange={(event) => set("min_date", event.target.value)}
            className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          To
          <input
            type="date"
            value={filters.max_date}
            onChange={(event) => set("max_date", event.target.value)}
            className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          User
          <select
            value={filters.user_id}
            onChange={(event) => set("user_id", event.target.value)}
            className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
          >
            <option value="">All users</option>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Type
          <select
            value={filters.type}
            onChange={(event) => set("type", event.target.value)}
            className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
          >
            <option value="">All types</option>
            {types.map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </select>
        </label>

        <Button type="submit" size="sm">
          Apply
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => {
            const cleared = { min_date: "", max_date: "", user_id: "", type: "" };
            setFilters(cleared);
            apply(cleared);
          }}
        >
          Clear
        </Button>
      </form>
    </Card>
  );
}
