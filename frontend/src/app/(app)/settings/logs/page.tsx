import type { Metadata } from "next";
import { LogViewer } from "./log-viewer";

export const metadata: Metadata = { title: "Logs" };

export default function LogsPage() {
  return <LogViewer />;
}
