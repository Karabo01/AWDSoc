import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { type EntityType, getAlert } from "@/api/alerts";
import { ApiError } from "@/api/client";
import { SeverityChip } from "@/components/SeverityChip";
import { TenantChip } from "@/components/TenantChip";

/** Every entity on this page is a link into the pivot. That is the whole reason
 *  `related.*` exists. */
function EntityLinks({
  type,
  values,
  label,
}: {
  type: EntityType;
  values: string[];
  label: string;
}) {
  if (values.length === 0) return null;
  return (
    <div className="mt-3">
      <p className="text-xs text-dim">{label}</p>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {values.map((value) => (
          <Link
            key={value}
            to={`/alerts?entity_type=${type}&entity_value=${encodeURIComponent(value)}`}
            className="data rounded border border-line bg-ink-900 px-1.5 py-0.5 text-xs transition hover:border-accent hover:text-accent"
          >
            {value}
          </Link>
        ))}
      </div>
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="data max-h-[32rem] overflow-auto rounded border border-line bg-ink-900 p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function AlertDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: alert, isLoading, error } = useQuery({
    queryKey: ["alert", id],
    queryFn: () => getAlert(id!),
    enabled: Boolean(id),
  });

  if (isLoading) return <p className="p-6 text-sm text-dim">Loading alert…</p>;
  if (error) {
    return (
      <p className="p-6 text-sm text-[color:var(--sev-crit)]">
        {error instanceof ApiError ? error.message : "Could not load this alert."}
      </p>
    );
  }
  if (!alert) return null;

  return (
    <div className="mx-auto max-w-6xl">
      <Link to="/alerts" className="text-sm text-dim transition hover:text-text">
        ← Alerts
      </Link>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <SeverityChip level={alert.rule_level} />
        <h1 className="text-lg font-semibold">{alert.rule_desc}</h1>
        <TenantChip name={alert.tenant_name} colour={alert.tenant_colour} />
      </div>

      <div className="data mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-dim">
        <span>rule {alert.rule_id}</span>
        <span>{new Date(alert.timestamp).toLocaleString()}</span>
        {alert.agent_name && <span>agent {alert.agent_name}</span>}
        <span>alert {alert.wazuh_id}</span>
        {alert.mitre_ids.length > 0 && <span>{alert.mitre_ids.join(", ")}</span>}
      </div>

      {alert.map_version < 0 && (
        <p className="mt-4 rounded border border-line bg-ink-800 p-3 text-sm">
          Normalisation failed for this alert, so the entity pivots below are empty. The
          raw alert is intact — fix the mapping and reprocess this time range to fill it
          in.
        </p>
      )}

      <div className="mt-6 rounded-lg border border-line bg-ink-800 p-4">
        <h2 className="text-sm font-medium">Entities</h2>
        <p className="mt-1 text-xs text-dim">
          Collected regardless of role. Click any value to see every alert touching it.
        </p>
        <EntityLinks type="ip" values={alert.related_ip} label="Addresses" />
        <EntityLinks type="user" values={alert.related_user} label="Users" />
        <EntityLinks type="host" values={alert.related_host} label="Hosts" />
        <EntityLinks type="hash" values={alert.related_hash} label="Hashes" />
        {alert.related_ip.length === 0 &&
          alert.related_user.length === 0 &&
          alert.related_host.length === 0 &&
          alert.related_hash.length === 0 && (
            <p className="mt-3 text-sm text-dim">
              No entities were extracted from this alert.
            </p>
          )}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div>
          <h2 className="text-sm font-medium">
            Normalised{" "}
            <span className="data text-xs text-dim">map v{alert.map_version}</span>
          </h2>
          <p className="mt-1 text-xs text-dim">
            Flat ECS keys, produced by the shared mapping.
          </p>
          <div className="mt-2">
            <Json value={alert.ecs} />
          </div>
        </div>
        <div>
          <h2 className="text-sm font-medium">Raw</h2>
          <p className="mt-1 text-xs text-dim">
            Exactly as the manager sent it. Never modified, which is what makes replay
            possible.
          </p>
          <div className="mt-2">
            <Json value={alert.raw} />
          </div>
        </div>
      </div>
    </div>
  );
}
