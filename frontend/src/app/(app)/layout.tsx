import { Shell } from "@/components/layout/shell";
import { apiFetch } from "@/lib/api";
import { ServiceTypesProvider } from "@/lib/service-types-context";
import { fetchServiceTypes } from "@/lib/service-types-server";
import type { Instance, User } from "@/lib/types";

/**
 * Signed-in shell. Loads only what the chrome needs — the current user, the
 * instance list for the sidebar and the service-type registry — all of
 * which the API already serves.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const [user, instances, types] = await Promise.all([
    apiFetch<User>("/users/me"),
    apiFetch<{ instances: Instance[] } | Instance[]>("/api/instances"),
    fetchServiceTypes(),
  ]);

  const list = Array.isArray(instances) ? instances : instances.instances;

  return (
    <ServiceTypesProvider value={types}>
      <Shell user={user} instances={list ?? []}>
        {children}
      </Shell>
    </ServiceTypesProvider>
  );
}
