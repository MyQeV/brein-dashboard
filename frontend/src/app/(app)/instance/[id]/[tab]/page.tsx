import type { Metadata } from "next";
import { DataTable } from "@/components/data-table";
import { Pagination } from "@/components/pagination";
import { Card } from "@/components/ui/card";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import { arrTabsFor, renderArrCell } from "@/lib/arr-tabs";
import { formatCount } from "@/lib/format";
import { buildQuery, clampPage, clampPageSize } from "@/lib/params";
import { fetchServiceTypes } from "@/lib/service-types-server";
import { appTimeZone } from "@/lib/timezone";
import type { InstanceDetail } from "@/lib/types";
import { SelectableArrTable } from "./selectable-table";
import { TabActions } from "./tab-actions";

/**
 * Generic list tab for Sonarr, Radarr and any service whose type declares
 * `arr_tables`.
 *
 * These endpoints proxy the upstream *arr APIs and share a response shape, so
 * one page driven by lib/arr-tabs.ts covers sixteen tabs. Anything with its
 * own behaviour (users, library, settings, the downloader tabs) has its own
 * route and is matched before this catch-all.
 */

type ArrResponse =
  | {
      records: Record<string, unknown>[];
      page?: number;
      pageSize?: number;
      totalRecords?: number;
    }
  | Record<string, unknown>[];

export async function generateMetadata(
  props: PageProps<"/instance/[id]/[tab]">,
): Promise<Metadata> {
  const { tab } = await props.params;
  return { title: tab.charAt(0).toUpperCase() + tab.slice(1) };
}

export default async function InstanceArrTabPage(
  props: PageProps<"/instance/[id]/[tab]">,
) {
  const { id, tab } = await props.params;
  const searchParams = await props.searchParams;

  const [instanceResult, types, prefs] = await Promise.all([
    softApiFetch<InstanceDetail>(`/api/instances/${id}`),
    fetchServiceTypes(),
    // Soft: the saved page size is a nicety, not a reason to lose the tab.
    softApiFetch<Record<string, unknown>>("/api/user/preferences"),
  ]);
  if (!instanceResult.ok) {
    return (
      <ApiNotice
        title="Instance"
        status={instanceResult.status}
        message={instanceResult.message}
      />
    );
  }
  const service = instanceResult.data.service_type.toLowerCase();
  const config = arrTabsFor(types, service, tab);

  if (!config) {
    return (
      <Card title="Not available">
        <p className="text-sm text-muted">This instance has no “{tab}” section.</p>
      </Card>
    );
  }

  const page = clampPage(searchParams.page);
  // The size saved on the profile page (`list_pagesize_<service>_<tab>`) is
  // the default; an explicit ?per_page= still wins. Clamped like the param,
  // since a stored value is no more trusted than a typed one.
  const saved = prefs.ok ? prefs.data[`list_pagesize_${service}_${tab}`] : undefined;
  const defaultPageSize = clampPageSize(
    typeof saved === "number" ? String(saved) : undefined,
  );
  const pageSize = clampPageSize(searchParams.per_page, defaultPageSize);
  const timeZone = appTimeZone();
  const query = config.paged
    ? buildQuery({ page, [config.pageSizeParam ?? "pageSize"]: pageSize })
    : "";

  const result = await softApiFetch<ArrResponse>(
    `/api/instances/${id}/${service}/${config.endpoint}${query}`,
  );
  if (!result.ok) {
    return (
      <ApiNotice title={config.title} status={result.status} message={result.message} />
    );
  }

  const data = result.data;
  const rows = Array.isArray(data) ? data : (data.records ?? []);
  const total = Array.isArray(data) ? rows.length : (data.totalRecords ?? rows.length);
  const basePath = `/instance/${id}/${tab}`;

  return (
    <Card
      title={`${config.title}${total ? ` (${formatCount(total)})` : ""}`}
      actions={
        config.commands || config.testAll ? (
          <TabActions
            instanceId={Number(id)}
            service={service}
            tab={tab}
            endpoint={config.endpoint}
            commands={config.commands ?? []}
            testAll={config.testAll}
          />
        ) : undefined
      }
    >
      {config.bulkDelete ? (
        // Keyed on the page: the selection is client state, and without this
        // ids ticked on page 1 stayed counted on page 2 with nothing visibly
        // checked, and "all selected" could be true with zero ticks showing.
        <SelectableArrTable
          key={`${tab}-${page}-${pageSize}`}
          instanceId={Number(id)}
          service={service}
          tab={tab}
          rows={rows}
          columns={config.columns}
          bulk={config.bulkDelete}
          empty={config.empty ?? "Nothing to show."}
        />
      ) : (
        <DataTable
          rows={rows}
          cards
          rowKey={(row, index) => String(row.id ?? index)}
          empty={config.empty ?? "Nothing to show."}
          columns={config.columns.map((column) => ({
            key: column.key,
            header: column.header,
            align: column.align,
            render: (row: Record<string, unknown>) =>
              renderArrCell(row, column, timeZone),
          }))}
        />
      )}
      {config.paged && (
        <Pagination
          basePath={basePath}
          query={{ per_page: pageSize }}
          page={page}
          pageSize={pageSize}
          total={total}
        />
      )}
    </Card>
  );
}
