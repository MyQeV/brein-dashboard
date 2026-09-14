"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

export function InstanceFilter({
  instances,
}: {
  instances: { id: number; label: string }[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const selected = params.get("instance_ids");

  function select(id: number | null) {
    const query = new URLSearchParams(params.toString());
    if (id === null) query.delete("instance_ids");
    else query.set("instance_ids", String(id));
    router.push(`${pathname}?${query.toString()}`);
  }

  if (instances.length === 0) return null;

  return (
    <fieldset className="flex flex-wrap gap-1 border-0 p-0">
      <legend className="sr-only">Filter by server</legend>
      <Button
        size="sm"
        variant={selected === null ? "primary" : "ghost"}
        aria-pressed={selected === null}
        onClick={() => select(null)}
      >
        All servers
      </Button>
      {instances.map((instance) => (
        <Button
          key={instance.id}
          size="sm"
          variant={selected === String(instance.id) ? "primary" : "ghost"}
          aria-pressed={selected === String(instance.id)}
          onClick={() => select(instance.id)}
        >
          {instance.label}
        </Button>
      ))}
    </fieldset>
  );
}
