import { cache } from "react";
import { apiFetch } from "@/lib/api";
import type { Instance } from "@/lib/types";

/**
 * GET /api/instances as a list, for server components. `cache` dedupes it
 * within one request, so the sidebar and a page filter both asking for it
 * costs one round trip.
 */
export const fetchInstances = cache(async (): Promise<Instance[]> => {
  const result = await apiFetch<{ instances: Instance[] } | Instance[]>("/api/instances");
  return Array.isArray(result) ? result : (result.instances ?? []);
});
