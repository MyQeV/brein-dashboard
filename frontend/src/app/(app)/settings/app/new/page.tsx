import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchServiceTypes } from "@/lib/service-types-server";
import { InstanceForm } from "../[id]/instance-form";

export const metadata: Metadata = { title: "Add app" };

/**
 * The add form for one service type. The instance does not exist until the
 * form is saved, and the form only saves once its connection test has
 * passed — so an app is either configured and reachable, or not there.
 */
export default async function NewInstancePage(props: PageProps<"/settings/app/new">) {
  const { type } = await props.searchParams;
  const serviceType = typeof type === "string" ? type : "";
  const types = await fetchServiceTypes();
  const service = types[serviceType];
  if (!service) notFound();

  return (
    <div className="flex max-w-xl flex-col gap-4">
      <Link href="/settings/app" className="text-sm text-muted hover:text-text">
        ← Back to apps
      </Link>
      <InstanceForm serviceType={service.id} serviceName={service.name} />
    </div>
  );
}
