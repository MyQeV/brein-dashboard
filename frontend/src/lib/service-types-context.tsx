"use client";

import { createContext, type ReactNode, useContext } from "react";
import type { ServiceTypeMap } from "@/lib/service-types";

const Ctx = createContext<ServiceTypeMap>({});

/** Loaded once by the app layout from GET /api/service-types. */
export function ServiceTypesProvider({
  value,
  children,
}: {
  value: ServiceTypeMap;
  children: ReactNode;
}) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useServiceTypes(): ServiceTypeMap {
  return useContext(Ctx);
}
