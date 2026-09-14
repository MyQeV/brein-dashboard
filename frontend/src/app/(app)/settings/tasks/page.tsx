import type { Metadata } from "next";
import { apiFetch } from "@/lib/api";
import type { ScheduledTask } from "@/lib/types";
import { TasksView } from "./tasks-view";

export const metadata: Metadata = { title: "Tasks" };

export default async function SettingsTasksPage() {
  const { tasks } = await apiFetch<{ tasks: ScheduledTask[] }>("/api/tasks");
  return <TasksView tasks={tasks} />;
}
