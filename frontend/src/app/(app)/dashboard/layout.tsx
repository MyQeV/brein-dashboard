import type { ReactNode } from "react";
import { DashboardNav } from "./dashboard-nav";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-4">
      <DashboardNav />
      {children}
    </div>
  );
}
