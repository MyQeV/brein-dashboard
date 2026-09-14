import { cache } from "react";
import { apiFetch } from "@/lib/api";
import type { ServiceTypeMap } from "@/lib/service-types";
import type { ServiceType } from "@/lib/types";

/**
 * GET /api/service-types as a map by id, for server components. `cache`
 * dedupes it within one request, so the layout and a page both asking for
 * it costs one round trip.
 */
export const fetchServiceTypes = cache(async (): Promise<ServiceTypeMap> => {
  const { service_types: list } = await apiFetch<{ service_types: ServiceType[] }>(
    "/api/service-types",
  );
  return Object.fromEntries(list.map((s) => [s.id, s]));
});
