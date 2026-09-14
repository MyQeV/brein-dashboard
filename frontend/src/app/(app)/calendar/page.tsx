import type { Metadata } from "next";
import { CalendarView } from "./calendar-view";

export const metadata: Metadata = { title: "Calendar" };

export default function CalendarPage() {
  return (
    <>
      <h1 className="mb-4 text-lg font-semibold">Release calendar</h1>
      <CalendarView />
    </>
  );
}
