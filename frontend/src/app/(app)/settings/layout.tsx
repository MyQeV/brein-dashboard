import type { ReactNode } from "react";
import { SettingsNav } from "./settings-nav";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold">Settings</h1>
      <SettingsNav />
      {children}
    </div>
  );
}
