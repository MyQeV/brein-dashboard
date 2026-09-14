import type { ReactNode } from "react";
import { apiFetch } from "@/lib/api";
import { serviceIcon } from "@/lib/service-types";
import { fetchServiceTypes } from "@/lib/service-types-server";
import type { InstanceDetail, User } from "@/lib/types";
import { externalHref } from "@/lib/url";
import { InstanceTabs } from "./instance-tabs";

export default async function InstanceLayout(
  props: LayoutProps<"/instance/[id]"> & { children: ReactNode },
) {
  const { id } = await props.params;
  const [instance, user, types] = await Promise.all([
    apiFetch<InstanceDetail>(`/api/instances/${id}`),
    apiFetch<User>("/users/me"),
    fetchServiceTypes(),
  ]);

  const icon = serviceIcon(types, instance.service_type);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          {icon && (
            // biome-ignore lint/performance/noImgElement: static SVG from FastAPI /static
            <img src={icon} alt="" aria-hidden="true" className="size-6" />
          )}
          {instance.label ?? instance.id}
        </h1>
        {externalHref(instance.app_url) && (
          <a
            href={externalHref(instance.app_url)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-muted hover:text-text"
          >
            Open app ↗
          </a>
        )}
        {!instance.is_configured && (
          <span className="text-sm text-warning">Not configured</span>
        )}
      </div>

      <InstanceTabs
        instanceId={instance.id}
        serviceType={instance.service_type}
        isAdmin={user.is_admin}
      />

      {props.children}
    </div>
  );
}
