"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { Select } from "@/components/ui/select";

export function UserPicker({
  basePath,
  users,
  selectedUserId,
  start,
  end,
}: {
  basePath: string;
  users: { id: string; name: string }[];
  selectedUserId: string | null;
  start: string;
  end: string;
}) {
  const router = useRouter();
  const [userId, setUserId] = useState(selectedUserId ?? "");
  const [from, setFrom] = useState(start);
  const [to, setTo] = useState(end);

  function apply(next: { user_id: string; start: string; end: string }) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value) params.set(key, value);
    }
    router.push(`${basePath}?${params.toString()}`);
  }

  return (
    <Card>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          apply({ user_id: userId, start: from, end: to });
        }}
      >
        <label htmlFor="user-dashboard-user" className="flex flex-col gap-1 text-sm">
          User
          <Select
            id="user-dashboard-user"
            size="sm"
            value={userId}
            onChange={(event) => {
              const next = event.target.value;
              setUserId(next);
              // Switch immediately: picking a user is the whole point of the
              // page, and making them press Apply as well is friction.
              apply({ user_id: next, start: from, end: to });
            }}
          >
            <option value="">Choose a user…</option>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </Select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          From
          <input
            type="date"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
            className={`${CONTROL_HEIGHT.sm} rounded-md border border-border bg-bg px-2 text-sm`}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          To
          <input
            type="date"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            className={`${CONTROL_HEIGHT.sm} rounded-md border border-border bg-bg px-2 text-sm`}
          />
        </label>

        <Button type="submit" size="sm">
          Apply range
        </Button>
      </form>
    </Card>
  );
}
