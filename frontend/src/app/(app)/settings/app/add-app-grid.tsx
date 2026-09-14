"use client";

import Link from "next/link";
import { serviceIcon } from "@/lib/service-types";
import { useServiceTypes } from "@/lib/service-types-context";
import type { ServiceType } from "@/lib/types";

/**
 * A tile per service type, each a link to the add form. Nothing is created
 * here: clicking used to insert an unconfigured instance and then open its
 * edit page, which left a half-made app behind whenever the page was closed
 * before the host and key were filled in.
 */
export function AddAppGrid({ serviceTypes }: { serviceTypes: ServiceType[] }) {
  const types = useServiceTypes();

  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-2">
      {serviceTypes.map((service) => {
        const icon = serviceIcon(types, service.id);
        return (
          <li key={service.id}>
            <Link
              href={`/settings/app/new?type=${encodeURIComponent(service.id)}`}
              className="flex w-full items-center gap-2 rounded-lg border border-border bg-bg p-3 text-left text-sm hover:border-accent"
            >
              {icon && (
                // biome-ignore lint/performance/noImgElement: static SVG from FastAPI /static
                <img src={icon} alt="" aria-hidden="true" className="size-5" />
              )}
              <span className="truncate">{service.name}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
