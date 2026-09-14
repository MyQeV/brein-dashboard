import type { Metadata } from "next";
import { SetupForm } from "./setup-form";

export const metadata: Metadata = { title: "First-time setup" };

export default function SetupPage() {
  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <SetupForm />
    </main>
  );
}
