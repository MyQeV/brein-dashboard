import { Shell } from "@/components/layout/shell";
import { fetchCurrentUser } from "@/lib/current-user-server";
import { fetchInstances } from "@/lib/instances-server";
import { ServiceTypesProvider } from "@/lib/service-types-context";
import { fetchServiceTypes } from "@/lib/service-types-server";
import { appTimeZone } from "@/lib/timezone";
import { TimeZoneProvider } from "@/lib/timezone-context";

/**
 * Signed-in shell. Loads only what the chrome needs — the current user, the
 * instance list for the sidebar and the service-type registry — all of
 * which the API already serves.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const [user, instances, types] = await Promise.all([
    fetchCurrentUser(),
    fetchInstances(),
    fetchServiceTypes(),
  ]);

  return (
    <TimeZoneProvider value={appTimeZone()}>
      <ServiceTypesProvider value={types}>
        <Shell user={user} instances={instances}>
          {children}
        </Shell>
      </ServiceTypesProvider>
    </TimeZoneProvider>
  );
}
