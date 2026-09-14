"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { CONTROL_HEIGHT } from "@/components/ui/control";
import { CARD_TABLE } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import type { AdminUser } from "@/lib/types";
import { updateUserRole } from "./actions";

const ROLES = ["admin", "user", "viewer"] as const;

function formatEpoch(value: number | null): string {
  if (!value) return "Never";
  return new Date(value * 1000).toLocaleString("en-GB", { timeZone: "UTC" });
}

export function UsersTable({
  users,
  currentUserId,
}: {
  users: AdminUser[];
  currentUserId: string;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  function change(user: AdminUser, patch: { role?: string; disabled?: boolean }) {
    setBusyId(user.id);
    setError(null);
    startTransition(async () => {
      const result = await updateUserRole(user.id, {
        role: patch.role ?? user.role,
        disabled: patch.disabled ?? user.disabled,
      });
      setBusyId(null);
      if (!result.ok) setError(result.error);
    });
  }

  return (
    <>
      {error && (
        <p role="alert" className="mb-2 text-sm text-error">
          {error}
        </p>
      )}
      <table className={CARD_TABLE.table}>
        <thead className={CARD_TABLE.thead}>
          <tr className="border-b border-border text-left">
            <th scope="col" className="px-3 py-2 font-medium text-muted">
              Username
            </th>
            <th scope="col" className="px-3 py-2 font-medium text-muted">
              Role
            </th>
            <th scope="col" className="px-3 py-2 font-medium text-muted">
              State
            </th>
            <th scope="col" className="px-3 py-2 font-medium text-muted">
              Last login
            </th>
            <th scope="col" className="px-3 py-2 font-medium text-muted">
              Failed
            </th>
          </tr>
        </thead>
        <tbody className={CARD_TABLE.tbody}>
          {users.map((user) => {
            const isSelf = user.id === currentUserId;
            const busy = busyId === user.id;
            return (
              <tr key={user.id} className={CARD_TABLE.row}>
                <td className={CARD_TABLE.lead}>
                  {user.username}
                  {isSelf && <span className="ml-2 text-xs text-muted">(you)</span>}
                </td>
                <td data-label="Role" className={CARD_TABLE.cell}>
                  <select
                    value={user.role}
                    aria-label={`Role for ${user.username}`}
                    // The API refuses self-edits; disabling here means the
                    // user is told why up front instead of by an error.
                    disabled={isSelf || busy}
                    title={isSelf ? "You cannot change your own role" : undefined}
                    onChange={(event) => change(user, { role: event.target.value })}
                    className={`${CONTROL_HEIGHT.sm} rounded-md border border-border bg-bg px-2 text-sm disabled:opacity-50`}
                  >
                    {ROLES.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </td>
                <td data-label="State" className={CARD_TABLE.cell}>
                  <Button
                    size="sm"
                    variant={user.disabled ? "secondary" : "ghost"}
                    disabled={isSelf || busy}
                    title={isSelf ? "You cannot disable your own account" : undefined}
                    onClick={() => change(user, { disabled: !user.disabled })}
                  >
                    {user.disabled ? "Disabled" : "Enabled"}
                  </Button>
                </td>
                <td data-label="Last login" className={cn(CARD_TABLE.cell, "text-muted")}>
                  {formatEpoch(user.last_login_at)}
                </td>
                <td
                  data-label="Failed logins"
                  className={cn(CARD_TABLE.cell, "tabular-nums text-muted")}
                >
                  {user.failed_login_attempts}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
