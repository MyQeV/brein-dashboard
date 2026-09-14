// REFERENCE LIST PAGE — copy this shape when porting another list.
//
// The order matters: resolve searchParams, clamp anything untrusted, build
// one query, fetch once, then render nav → table → pagination. `headerQuery`
// deliberately omits sort_by, sort_dir and page, since those are what the
// column headers set.

import type { Metadata } from "next";
import { DataTable } from "@/components/data-table";
import { Pagination } from "@/components/pagination";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import {
  buildQuery,
  clampPage,
  clampPageSize,
  DEFAULT_PAGE_SIZE,
  firstParam,
} from "@/lib/params";
import { Backups } from "./backups";
import { TablePicker } from "./table-picker";

export const metadata: Metadata = { title: "Database" };

type Row = Record<string, string | number | null>;
type RowsResponse = { rows: Row[]; columns: string[]; total: number };

const BASE_PATH = "/settings/database";

export default async function DatabasePage(props: PageProps<"/settings/database">) {
  // params and searchParams are Promises in Next 16.
  const searchParams = await props.searchParams;

  const { tables } = await apiFetch<{ tables: string[] }>("/api/database/tables");
  const requested = firstParam(searchParams.table);
  const table = requested && tables.includes(requested) ? requested : tables[0];

  const page = clampPage(searchParams.page);
  const perPage = clampPageSize(searchParams.per_page, DEFAULT_PAGE_SIZE);
  const sortBy = firstParam(searchParams.sort_by);
  const sortDir = firstParam(searchParams.sort_dir) === "desc" ? "desc" : "asc";

  const data = table
    ? await apiFetch<RowsResponse>(
        `/api/database/tables/${encodeURIComponent(table)}/rows${buildQuery({
          page,
          per_page: perPage,
          sort_by: sortBy,
          sort_dir: sortDir,
        })}`,
      )
    : { rows: [], columns: [], total: 0 };

  return (
    <div className="flex flex-col gap-4">
      <TablePicker tables={tables} current={table ?? ""} />

      <Card title={table ?? "No tables"}>
        <DataTable<Row>
          rows={data.rows}
          columns={data.columns.map((name) => ({ key: name, header: name }))}
          basePath={BASE_PATH}
          headerQuery={{ table, per_page: perPage }}
          sortBy={sortBy}
          sortDir={sortDir}
          rowKey={(row, index) => String(row.id ?? index)}
          empty="This table has no rows."
        />
        <Pagination
          basePath={BASE_PATH}
          query={{ table, per_page: perPage, sort_by: sortBy, sort_dir: sortDir }}
          page={page}
          pageSize={perPage}
          total={data.total}
        />
      </Card>

      <Backups />
    </div>
  );
}
