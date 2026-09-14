import type { Metadata } from "next";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import type { DownloadQueue } from "@/lib/types";
import { QueueView } from "./queue-view";

export const metadata: Metadata = { title: "Queue" };

export default async function DownloadQueuePage(
  props: PageProps<"/instance/[id]/dl-queue">,
) {
  const { id } = await props.params;
  const result = await softApiFetch<DownloadQueue>(
    `/api/instances/${id}/downloads/queue`,
  );

  if (!result.ok) {
    return <ApiNotice title="Queue" status={result.status} message={result.message} />;
  }

  return <QueueView instanceId={Number(id)} queue={result.data} />;
}
