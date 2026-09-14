import type { Metadata } from "next";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { serviceIcon } from "@/lib/service-types";
import { fetchServiceTypes } from "@/lib/service-types-server";
import type { Instance } from "@/lib/types";
import { AddAppGrid } from "./add-app-grid";

export const metadata: Metadata = { title: "Apps" };

export default async function SettingsAppPage() {
  const [types, instancesResponse] = await Promise.all([
    fetchServiceTypes(),
    apiFetch<{ instances: Instance[] } | Instance[]>("/api/instances"),
  ]);
  const service_types = Object.values(types);

  const instances = Array.isArray(instancesResponse)
    ? instancesResponse
    : (instancesResponse.instances ?? []);

  return (
    <div className="flex flex-col gap-6">
      <Card title="Add app">
        <p className="mb-3 text-sm text-muted">
          Pick a type to create an instance, then configure its connection.
        </p>
        <AddAppGrid serviceTypes={service_types} />
      </Card>

      <Card title="Configured apps">
        {instances.length === 0 ? (
          <p className="text-sm text-muted">No apps yet. Add one above.</p>
        ) : (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
            {instances.map((instance) => {
              const icon = serviceIcon(types, instance.service_type);
              return (
                <li key={instance.id}>
                  <Link
                    href={`/settings/app/${instance.id}`}
                    className="flex h-full flex-col gap-1 rounded-lg border border-border bg-bg p-3 hover:border-accent"
                  >
                    <span className="flex items-center gap-2">
                      {icon && (
                        // biome-ignore lint/performance/noImgElement: static SVG from FastAPI /static
                        <img src={icon} alt="" aria-hidden="true" className="size-5" />
                      )}
                      <span className="truncate font-medium">
                        {instance.label ?? instance.id}
                      </span>
                      <span
                        role="img"
                        aria-label={instance.active ? "Active" : "Inactive"}
                        className={`ml-auto size-2 shrink-0 rounded-full ${
                          instance.active ? "bg-success" : "bg-muted"
                        }`}
                      />
                    </span>
                    <span className="text-xs text-muted">
                      {instance.service_name ?? instance.service_type}
                      {instance.is_configured ? "" : " • not configured"}
                    </span>
                    <span className="text-xs text-muted">
                      Order: {(instance.sort_order ?? 0) + 1}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
