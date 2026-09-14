import { redirect } from "next/navigation";

/** `/settings` has no content of its own; App is the first tab. */
export default function SettingsIndex() {
  redirect("/settings/app");
}
