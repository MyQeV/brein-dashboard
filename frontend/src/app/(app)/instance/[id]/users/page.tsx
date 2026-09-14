import type { Metadata } from "next";
import { Card } from "@/components/ui/card";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import type { InstanceDetail, MediaUser, MediaUsersResponse } from "@/lib/types";
import { UsersTable } from "./users-table";

export const metadata: Metadata = { title: "Users" };

/** The services whose accounts live on the server, so Brein can edit them. */
const EDITABLE_SERVICES = new Set(["emby", "jellyfin"]);

export default async function InstanceUsersPage(
  props: PageProps<"/instance/[id]/users">,
) {
  const { id } = await props.params;
  const [result, instanceResult] = await Promise.all([
    softApiFetch<MediaUsersResponse>(`/api/instances/${id}/users`),
    softApiFetch<InstanceDetail>(`/api/instances/${id}`),
  ]);

  if (!result.ok) {
    return <ApiNotice title="Users" status={result.status} message={result.message} />;
  }
  const data = result.data;

  if ("supported" in data && data.supported === false) {
    return (
      <Card title="Users">
        <p className="text-sm text-muted">This service does not expose a user list.</p>
      </Card>
    );
  }

  const { users, libraries } = data as Extract<
    MediaUsersResponse,
    { users: MediaUser[] }
  >;
  // Plex accounts belong to plex.tv rather than to the server, so there is
  // nothing here to edit even though the list renders.
  const canEdit =
    instanceResult.ok &&
    EDITABLE_SERVICES.has(instanceResult.data.service_type.toLowerCase());

  return (
    <Card title={`Users (${users.length})`}>
      <UsersTable
        instanceId={Number(id)}
        users={users}
        libraries={libraries}
        canEdit={canEdit}
        // The app's zone — the same TZ the API runs on, as the dashboard
        // pages resolve it.
        timeZone={process.env.TZ || "UTC"}
      />
    </Card>
  );
}
