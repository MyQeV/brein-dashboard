import type { Metadata } from "next";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/current-user-server";
import type { AdminUser } from "@/lib/types";
import { AddUserForm } from "./add-user-form";
import { UsersTable } from "./users-table";

export const metadata: Metadata = { title: "Users" };

export default async function SettingsUsersPage() {
  const [{ users }, me] = await Promise.all([
    apiFetch<{ users: AdminUser[] }>("/api/users"),
    fetchCurrentUser(),
  ]);

  return (
    <div className="flex flex-col gap-4">
      <Card title={`Users (${users.length})`}>
        <UsersTable users={users} currentUserId={me.id} />
      </Card>
      <AddUserForm />
    </div>
  );
}
