"use client";

import { createContext, type ReactNode, useContext } from "react";
import type { NowPlayingSession } from "@/lib/types";
import { type NowPlayingConnection, useNowPlaying } from "@/lib/use-now-playing";

type Value = {
  sessions: NowPlayingSession[];
  connection: NowPlayingConnection;
  /** False until the first payload; see useNowPlaying. */
  loaded: boolean;
};

const NowPlayingContext = createContext<Value | null>(null);

/** One socket for the whole shell; the sidebar, its drawer copy and the Now playing page all read it. */
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
