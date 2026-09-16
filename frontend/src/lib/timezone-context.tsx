"use client";

import { createContext, type ReactNode, useContext } from "react";

const Ctx = createContext("UTC");

/** The app zone, resolved once by the app layout from `appTimeZone()`. */
export function TimeZoneProvider({
  value,
  children,
}: {
  value: string;
  children: ReactNode;
}) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTimeZone(): string {
  return useContext(Ctx);
}
