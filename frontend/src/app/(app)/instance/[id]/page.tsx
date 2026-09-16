import { redirect } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/current-user-server";
import { defaultTab } from "@/lib/service-types";
import { fetchServiceTypes } from "@/lib/service-types-server";
import type { InstanceDetail } from "@/lib/types";

/** No content of its own; land on the service's first tab. */
export default async function InstanceIndex(props: PageProps<"/instance/[id]">) {
  const { id } = await props.params;
  const [instance, user, types] = await Promise.all([
    apiFetch<InstanceDetail>(`/api/instances/${id}`),
    fetchCurrentUser(),
    fetchServiceTypes(),
  ]);
  redirect(`/instance/${id}/${defaultTab(types, instance.service_type, user.is_admin)}`);
}
