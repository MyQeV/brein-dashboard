import type { Metadata } from "next";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { InstanceDetail } from "@/lib/types";
import { InstanceForm } from "./instance-form";

export const metadata: Metadata = { title: "Instance" };

export default async function InstanceEditPage(props: PageProps<"/settings/app/[id]">) {
  const { id } = await props.params;
  const instance = await apiFetch<InstanceDetail>(`/api/instances/${id}`);

  return (
    <div className="flex max-w-xl flex-col gap-4">
      <Link href="/settings/app" className="text-sm text-muted hover:text-text">
        ← Back to apps
      </Link>
      <InstanceForm instance={instance} />
    </div>
  );
}
