import type { Metadata } from "next";
import { apiFetch } from "@/lib/api";
import type { SystemSetting } from "@/lib/types";
import { ConfigForm } from "./config-form";

export const metadata: Metadata = { title: "Config" };

export default async function SettingsConfigPage() {
  const settings = await apiFetch<SystemSetting[]>("/api/settings/system");
  return <ConfigForm settings={settings} />;
}
