import type { Metadata } from "next";
import { DataTable } from "@/components/data-table";
import { Card } from "@/components/ui/card";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import type { MediaLibrary } from "@/lib/types";

export const metadata: Metadata = { title: "Library" };

type Response = { supported: false } | { libraries: MediaLibrary[] };

export default async function InstanceLibraryPage(
  props: PageProps<"/instance/[id]/library">,
) {
  const { id } = await props.params;
  const result = await softApiFetch<Response>(`/api/instances/${id}/libraries`);

  if (!result.ok) {
    return <ApiNotice title="Library" status={result.status} message={result.message} />;
  }
  const data = result.data;

  if ("supported" in data && data.supported === false) {
    return (
      <Card title="Library">
        <p className="text-sm text-muted">This service does not expose a library list.</p>
      </Card>
    );
  }

  const libraries = (data as { libraries: MediaLibrary[] }).libraries;

  return (
    <Card title={`Libraries (${libraries.length})`}>
      <DataTable<MediaLibrary & Record<string, unknown>>
        rows={libraries as (MediaLibrary & Record<string, unknown>)[]}
        rowKey={(row) => row.id}
        empty="No libraries found."
        columns={[
          { key: "name", header: "Name" },
          {
            key: "collection_type",
            header: "Type",
            render: (row) => row.collection_type ?? row.type ?? "—",
          },
          { key: "id", header: "Id" },
        ]}
      />
    </Card>
  );
}
