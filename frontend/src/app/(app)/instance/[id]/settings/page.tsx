import type { Metadata } from "next";
import { Card } from "@/components/ui/card";
import { ApiNotice } from "@/components/ui/notice";
import { softApiFetch } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { InstanceDetail } from "@/lib/types";
import { HostConfigForm } from "./host-config-form";
import { InstanceActions } from "./instance-actions";

export const metadata: Metadata = { title: "Settings" };

type SettingsInfo = {
  settings_system_info: Record<string, unknown> | null;
  settings_public_info: Record<string, unknown> | null;
  settings_health: Record<string, unknown>[] | null;
  settings_host_config: Record<string, unknown> | null;
  settings_sab_status: Record<string, unknown> | null;
  settings_sab_server_stats: Record<string, unknown> | null;
  settings_sabnzbd_stats_snapshot: Record<string, unknown> | null;
  settings_fetch_error: string | null;
};

/** Show the handful of fields that are actually useful, not the whole payload. */
const INTERESTING = [
  "version",
  "appName",
  "instanceName",
  "startTime",
  "osName",
  "osVersion",
  "runtimeVersion",
  "isDebug",
  "ServerName",
  "OperatingSystem",
  "Id",
];

function InfoList({ data }: { data: Record<string, unknown> }) {
  const entries = INTERESTING.filter((key) => data[key] !== undefined).map(
    (key) => [key, data[key]] as const,
  );
  const rows = entries.length > 0 ? entries : Object.entries(data).slice(0, 10);

  return (
    <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-muted">{key}</dt>
          <dd className="truncate">{value === null ? "—" : String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default async function InstanceSettingsPage(
  props: PageProps<"/instance/[id]/settings">,
) {
  const { id } = await props.params;

  const [instanceResult, infoResult] = await Promise.all([
    softApiFetch<InstanceDetail>(`/api/instances/${id}`),
    softApiFetch<SettingsInfo>(`/api/instances/${id}/settings-info`),
  ]);

  if (!instanceResult.ok) {
    return (
      <ApiNotice
        title="Settings"
        status={instanceResult.status}
        message={instanceResult.message}
      />
    );
  }
  const instance = instanceResult.data;
  const service = instance.service_type.toLowerCase();

  if (!infoResult.ok) {
    return (
      <div className="flex flex-col gap-4">
        <ApiNotice
          title="System information"
          status={infoResult.status}
          message={infoResult.message}
        />
        <InstanceActions instanceId={instance.id} serviceType={service} />
      </div>
    );
  }

  const info = infoResult.data;
  const system = info.settings_system_info;

  return (
    <div className="flex flex-col gap-4">
      {info.settings_fetch_error && (
        <Card title="System information">
          <p className="text-sm text-warning">{info.settings_fetch_error}</p>
        </Card>
      )}

      {system && (
        <Card title="System information">
          <InfoList data={system} />
        </Card>
      )}

      {info.settings_public_info && (
        <Card title="Public information">
          <InfoList data={info.settings_public_info} />
        </Card>
      )}

      {info.settings_health && info.settings_health.length > 0 && (
        <Card title={`Health (${info.settings_health.length})`}>
          <ul className="flex flex-col gap-2 text-sm">
            {info.settings_health.map((entry, index) => (
              <li key={String(entry.message ?? index)} className="flex flex-col gap-0.5">
                <span className="text-warning">{String(entry.type ?? "issue")}</span>
                <span>{String(entry.message ?? "")}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {info.settings_sab_status && (
        <Card title="SABnzbd status">
          <InfoList data={info.settings_sab_status} />
        </Card>
      )}

      {info.settings_sabnzbd_stats_snapshot && (
        <Card title="Stored download totals">
          <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1 text-sm">
            {Object.entries(info.settings_sabnzbd_stats_snapshot).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted">{key}</dt>
                <dd className="tabular-nums">
                  {typeof value === "number" && key.includes("byte")
                    ? formatBytes(value)
                    : String(value ?? "—")}
                </dd>
              </div>
            ))}
          </dl>
        </Card>
      )}

      {info.settings_host_config && (
        <HostConfigForm
          instanceId={instance.id}
          serviceType={service}
          config={info.settings_host_config}
        />
      )}

      <InstanceActions instanceId={instance.id} serviceType={service} />
    </div>
  );
}
