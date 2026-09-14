import type { ServiceType, Tab } from "@/lib/types";

/** GET /api/service-types keyed by id; see service-types-server.ts and service-types-context.tsx. */
export type ServiceTypeMap = Record<string, ServiceType>;

export function serviceIcon(
  types: ServiceTypeMap,
  serviceType: string | null | undefined,
): string | undefined {
  const id = (serviceType ?? "").toLowerCase();
  return types[id]?.icon ? `/static/icons/${id}.svg` : undefined;
}

export function tabsFor(
  types: ServiceTypeMap,
  serviceType: string,
  isAdmin = true,
): Tab[] {
  const all = types[serviceType.toLowerCase()]?.tabs ?? [];
  return isAdmin ? all : all.filter((tab) => !tab.admin_only);
}

export function defaultTab(
  types: ServiceTypeMap,
  serviceType: string,
  isAdmin = true,
): string {
  return tabsFor(types, serviceType, isAdmin)[0]?.slug ?? "overview";
}

/** Category ids in the order the sidebar shows them, from the types that exist. */
export const CATEGORY_ORDER = [
  "media_servers",
  "media_management",
  "downloaders",
  "user_management",
];
export const CATEGORY_LABELS: Record<string, string> = {
  media_servers: "Media servers",
  media_management: "Media management",
  downloaders: "Downloaders",
  user_management: "User management",
};
