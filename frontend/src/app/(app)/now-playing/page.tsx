import type { Metadata } from "next";
import { apiFetch } from "@/lib/api";
import type { NowPlayingSession } from "@/lib/types";
import { NowPlayingView } from "./now-playing-view";

export const metadata: Metadata = { title: "Now playing" };

export default async function NowPlayingPage() {
  // Rendered once on the server so the first paint has content; the socket
  // takes over from there.
  const { items } = await apiFetch<{ items: NowPlayingSession[] }>("/api/now-playing");
  return <NowPlayingView initialSessions={items} />;
}
