"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { serviceIcon } from "@/lib/service-types";
import { useServiceTypes } from "@/lib/service-types-context";
import type { ServiceType } from "@/lib/types";
import { addInstance } from "./actions";

export function AddAppGrid({ serviceTypes }: { serviceTypes: ServiceType[] }) {
  const router = useRouter();
  const types = useServiceTypes();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  function add(serviceType: string) {
    setPendingId(serviceType);
    setError(null);
    startTransition(async () => {
      const result = await addInstance(serviceType);
      setPendingId(null);
      if (result.ok && result.id) {
        // Straight to the edit form: a new instance is useless until it has a
        // host and key, which is what the old flow did too.
        router.push(`/settings/app/${result.id}`);
      } else if (!result.ok) {
        setError(result.error);
      }
    });
  }

  return (
    <>
      {error && (
        <p role="alert" className="mb-2 text-sm text-error">
          {error}
        </p>
      )}
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-2">
        {serviceTypes.map((service) => {
          const icon = serviceIcon(types, service.id);
          return (
            <li key={service.id}>
              <button
                type="button"
                disabled={pendingId !== null}
                onClick={() => add(service.id)}
                className="flex w-full items-center gap-2 rounded-lg border border-border bg-bg p-3 text-left text-sm hover:border-accent disabled:opacity-50"
              >
                {icon && (
                  // biome-ignore lint/performance/noImgElement: static SVG from FastAPI /static
                  <img src={icon} alt="" aria-hidden="true" className="size-5" />
                )}
                <span className="truncate">
                  {pendingId === service.id ? "Adding…" : service.name}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}
