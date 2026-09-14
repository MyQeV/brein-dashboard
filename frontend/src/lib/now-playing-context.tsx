"use client";

import { createContext, type ReactNode, useContext } from "react";
import type { NowPlayingSession } from "@/lib/types";
import { type NowPlayingConnection, useNowPlaying } from "@/lib/use-now-playing";

type Value = { sessions: NowPlayingSession[]; connection: NowPlayingConnection };

const NowPlayingContext = createContext<Value | null>(null);

/** One socket for the whole shell; the sidebar (and its drawer copy) read it. */
export function NowPlayingProvider({ children }: { children: ReactNode }) {
  const value = useNowPlaying();
  return (
    <NowPlayingContext.Provider value={value}>{children}</NowPlayingContext.Provider>
  );
}

export function useNowPlayingContext(): Value {
  const value = useContext(NowPlayingContext);
  if (!value) throw new Error("useNowPlayingContext outside NowPlayingProvider");
  return value;
}
