import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { rootGet } from "@/api/client";
import type { Health } from "@/api/types";
import { getIngestStatus } from "@/api/ingest";
import { useAuth } from "@/hooks/useAuth";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-ink-800 p-4">
      <p className="text-sm text-dim">{label}</p>
      <p className="data mt-2 text-2xl">{value}</p>
      {hint && <p className="mt-1 text-xs text-dim">{hint}</p>}
    </div>
  );
}

export function Overview() {
  const { user } = useAuth();
  const { data: ingest } = useQuery({
    queryKey: ["ingest-status"],
    queryFn: getIngestStatus,
    refetchInterval: 30_000,
    enabled: Boolean(user?.is_staff),
  });
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => rootGet<Health>("/healthz"),
    refetchInterval: 30_000,
  });

  const scope = user?.is_staff
    ? user.active_tenant
      ? (user.tenants.find((t) => t.id === user.active_tenant)?.name ?? "One client")
      : "All clients"
    : "Your environment";

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold">Overview</h1>
      <p className="mt-1 text-sm text-dim">{scope}</p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Open incidents" value="—" hint="Arrives with M5" />
        <Tile
          label="Alerts today"
          value={
            ingest
              ? ingest.tenants.reduce((n, t) => n + t.alerts_today, 0).toLocaleString()
              : "…"
          }
          hint={
            ingest && ingest.backlog > 0
              ? `${ingest.backlog.toLocaleString()} queued for writing`
              : undefined
          }
        />
        <Tile
          label="Clients delivering"
          value={
            ingest
              ? `${ingest.tenants.filter((t) => !t.silent).length}/${ingest.tenants.length}`
              : "…"
          }
          hint={
            ingest && ingest.tenants.some((t) => t.silent)
              ? "Some clients have never delivered an alert"
              : undefined
          }
        />
        <Tile
          label="Platform"
          value={health ? (health.status === "ok" ? "Healthy" : "Degraded") : "…"}
          hint={
            health
              ? `postgres ${health.postgres.ok ? "up" : "down"} · redis ${
                  health.redis.ok ? "up" : "down"
                } · worker ${health.worker.alive ? "alive" : "quiet"}`
              : undefined
          }
        />
      </div>

      {ingest && ingest.tenants.length > 0 && (
        <div className="mt-8 rounded-lg border border-line bg-ink-800">
          <p className="border-b border-line px-4 py-3 text-sm font-medium">Ingest</p>
          {ingest.tenants.map((tenant) => (
            <div
              key={tenant.tenant_id}
              className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line px-4 py-3 last:border-b-0"
            >
              <span className="min-w-40 flex-1 text-sm">{tenant.name}</span>
              <span className="data text-xs text-dim">
                {tenant.alerts_today.toLocaleString()} today
              </span>
              <span className="data text-xs text-dim">
                {tenant.last_alert_at
                  ? `last ${new Date(tenant.last_alert_at).toLocaleString()}`
                  : "never delivered"}
              </span>
              {tenant.silent && (
                <span className="text-xs text-[color:var(--sev-med)]">
                  Check the integration block on their manager
                </span>
              )}
              {tenant.failed_normalisation > 0 && (
                <Link
                  to="/alerts?map_version=-1"
                  className="text-xs text-[color:var(--sev-high)] underline transition hover:brightness-125"
                >
                  {tenant.failed_normalisation} failed to normalise
                </Link>
              )}
            </div>
          ))}
        </div>
      )}

      {ingest && ingest.tenants.length === 0 && (
        <p className="mt-8 text-sm text-dim">
          No clients yet. Onboard one, then install the integrator on their manager to
          start receiving alerts.
        </p>
      )}
    </div>
  );
}
