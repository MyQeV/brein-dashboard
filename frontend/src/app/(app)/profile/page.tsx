import type { Metadata } from "next";
import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";
import { ListPreferences } from "./list-preferences";
import { PasswordForm } from "./password-form";
import { ProfileForm } from "./profile-form";

export const metadata: Metadata = { title: "Profile" };

export default async function ProfilePage() {
  const user = await apiFetch<User>("/users/me");

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <h1 className="text-lg font-semibold">Profile</h1>
      <ProfileForm user={user} />
      <PasswordForm />
      <ListPreferences />
    </div>
  );
}
