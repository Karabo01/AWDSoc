import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy } from "react";
import { Link } from "react-router-dom";

import { rootGet } from "@/api/client";
import { getOverview, getTrend } from "@/api/overview";
import type { Health } from "@/api/types";
import { Empty, ErrorNote, Freshness, Loading, relative } from "@/components/States";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

/** Charting is ~400 kB of the bundle and only this page uses it. Splitting it
 *  out keeps the queue - the page an analyst actually opens first and leaves
 *  open - from paying for a library it never renders. */
const TrendCharts = lazy(() =>
  import("@/components/TrendCharts").then((m) => ({ default: m.TrendCharts })),
);

function Tile({
  label,
  value,
  hint,
  to,
  tone,
}: {
  label: string;
  value: string | number;
  hint?: string;
  to?: string;
  tone?: "warn" | "bad";
}) {
  const colour =
    tone === "bad"
      ? "text-[color:var(--sev-crit)]"
      : tone === "warn"
        ? "text-[color:var(--sev-med)]"
        : "";
  const body = (
    <div className="h-full rounded-lg border border-line bg-ink-800 p-4 transition hover:border-accent/40">
      <p className="text-sm text-dim">{label}</p>
      <p className={`data mt-2 text-2xl ${colour}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-dim">{hint}</p>}
    </div>
  );
  return to ? (
    <Link to={to} className="block outline-none focus-visible:ring-1 focus-visible:ring-accent">
      {body}
    </Link>
  ) : (
    body
  );
}

export function Overview() {
  const { user } = useAuth();

  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
    refetchInterval: 60_000,
  });

  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => rootGet<Health>("/api/healthz"),
    refetchInterval: 30_000,
  });

  const trend = useQuery({
    queryKey: ["overview-trend"],
    queryFn: () => getTrend(7),
    refetchInterval: 300_000,
  });

  const data = overview.data;
  const scope = user?.is_staff
    ? user.active_tenant
      ? (user.tenants.find((t) => t.id === user.active_tenant)?.name ?? "One client")
      : "All clients"
    : "Your environment";

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold">Overview</h1>
      <p className="mt-1 text-sm text-dim">{scope}</p>

      {overview.isLoading && <Loading what="overview" />}
      {overview.error && (
        <ErrorNote
          error={overview.error}
          fallback="Could not load the overview."
          onRetry={() => void overview.refetch()}
        />
      )}

      {/* The one thing on this page that is not a metric. A misgrouped agent is a
          cross-tenant leak in progress, so it goes above everything else. */}
      {data && data.misgrouped_agents.length > 0 && (
        <div
          role="alert"
          className="mt-6 rounded-lg border border-[color:var(--sev-crit)] bg-ink-800 p-4"
        >
          <p className="text-sm font-medium text-[color:var(--sev-crit)]">
            {data.misgrouped_agents.length} agent
            {data.misgrouped_agents.length > 1 ? "s are" : " is"} visible to more than
            one client.
          </p>
          <p className="mt-1 max-w-prose text-sm text-dim">
            Agent IDs are unique within a manager, so this means two clients&rsquo; agent
            groups overlap on the same manager. One of them is receiving the
            other&rsquo;s alerts, and no ingest check can catch it — the{" "}
            <span className="data">&lt;group&gt;</span> filter in{" "}
            <span className="data">ossec.conf</span> decides which client an alert is
            posted to.
          </p>
          <ul className="mt-2 space-y-1 text-xs">
            {data.misgrouped_agents.slice(0, 8).map((agent) => (
              <li key={`${agent.base_url}:${agent.agent_id}`}>
                <Link
                  to={`/agents/${encodeURIComponent(agent.agent_id)}`}
                  className="data underline transition hover:text-accent"
                >
                  {agent.agent_name ?? agent.agent_id}
                </Link>
                <span className="text-dim">
                  {" "}
                  — shared between {agent.tenant_slugs.join(", ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data && (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Tile
            label="Open incidents"
            value={data.open_incidents.toLocaleString()}
            to="/incidents"
            hint={data.critical_open > 0 ? `${data.critical_open} at level 13+` : undefined}
            tone={data.critical_open > 0 ? "warn" : undefined}
          />
          <Tile
            label="Response breached"
            value={data.response_breached}
            to="/incidents?status=new&status=active"
            hint={
              data.at_risk > 0
                ? `${data.at_risk} more due within the hour`
                : "Cases paused awaiting a client cannot breach."
            }
            tone={
              data.response_breached > 0 ? "bad" : data.at_risk > 0 ? "warn" : undefined
            }
          />
          <Tile
            label="Alerts, last 24h"
            value={data.alerts_24h.toLocaleString()}
            to="/alerts"
          />
          <Tile
            label="Platform"
            value={
              health.data ? (health.data.status === "ok" ? "Healthy" : "Degraded") : "…"
            }
            hint={
              health.data
                ? `postgres ${health.data.postgres.ok ? "up" : "down"} · redis ${
                    health.data.redis.ok ? "up" : "down"
                  } · worker ${health.data.worker.alive ? "alive" : "quiet"}`
                : undefined
            }
            tone={health.data && health.data.status !== "ok" ? "bad" : undefined}
          />
        </div>
      )}

      {trend.data && trend.data.buckets.length > 0 && (
        <Suspense
          fallback={<div className="mt-6 h-44 rounded-lg border border-line bg-ink-800" />}
        >
          <TrendCharts trend={trend.data} />
        </Suspense>
      )}

      {data && data.tenants.length === 0 && (
        <Empty
          title="No clients yet."
          hint="Onboard one, then install the integrator on their manager to start receiving alerts."
          action={
            user?.role === "platform_admin" ? (
              <Link
                to="/settings/tenants"
                className="rounded border border-line px-3 py-1.5 text-sm transition hover:text-accent"
              >
                Add a client
              </Link>
            ) : undefined
          }
        />
      )}

      {data && data.tenants.length > 0 && (
        <div className="mt-8 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[52rem] border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-ink-800">
              <tr className="border-b border-line text-left text-dim">
                <th className="px-3 py-2 text-xs font-medium">
                  {data.scope === "fleet" ? "Client" : "Environment"}
                </th>
                <th className="px-3 py-2 text-xs font-medium">Open</th>
                <th className="px-3 py-2 text-xs font-medium">Breached</th>
                <th className="px-3 py-2 text-xs font-medium">Awaiting client</th>
                <th className="px-3 py-2 text-xs font-medium">Alerts 24h</th>
                <th className="px-3 py-2 text-xs font-medium">Agents</th>
                <th className="px-3 py-2 text-xs font-medium">Health</th>
              </tr>
            </thead>
            <tbody>
              {data.tenants.map((tenant) => (
                <tr
                  key={tenant.tenant_id}
                  className="border-b border-line last:border-b-0"
                  style={{ boxShadow: `inset 3px 0 0 ${tenant.colour ?? "transparent"}` }}
                >
                  <td className="px-3 py-1.5">
                    <TenantChip name={tenant.name} colour={tenant.colour} />
                    {tenant.status !== "active" && (
                      <span className="ml-2 text-xs text-dim">{tenant.status}</span>
                    )}
                  </td>
                  <td className="data px-3 py-1.5 text-xs">
                    {tenant.open_incidents}
                    {tenant.unassigned_incidents > 0 && (
                      <span className="ml-1 text-dim">
                        ({tenant.unassigned_incidents} unassigned)
                      </span>
                    )}
                  </td>
                  <td className="data px-3 py-1.5 text-xs">
                    {tenant.response_breached > 0 ? (
                      <span className="text-[color:var(--sev-crit)]">
                        {tenant.response_breached}
                      </span>
                    ) : !tenant.has_sla ? (
                      <span className="text-dim" title="This client has no SLA policy">
                        no SLA
                      </span>
                    ) : (
                      <span className="text-dim">0</span>
                    )}
                  </td>
                  <td className="data px-3 py-1.5 text-xs text-dim">
                    {tenant.awaiting_client || "—"}
                  </td>
                  <td className="data px-3 py-1.5 text-xs text-dim">
                    {tenant.alerts_24h.toLocaleString()}
                  </td>
                  <td className="data px-3 py-1.5 text-xs text-dim">
                    {tenant.has_connection ? (
                      <>
                        {tenant.agents_active}/{tenant.agents_total}
                        {tenant.agents_disconnected > 0 && (
                          <span className="ml-1 text-[color:var(--sev-med)]">
                            {tenant.agents_disconnected} down
                          </span>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-xs">
                    {tenant.silent ? (
                      <span className="text-[color:var(--sev-med)]">
                        {tenant.last_alert_at
                          ? `silent since ${relative(tenant.last_alert_at)}`
                          : "never delivered"}
                      </span>
                    ) : tenant.last_sync_error ? (
                      <span
                        className="text-[color:var(--sev-high)]"
                        title={tenant.last_sync_error}
                      >
                        manager unreachable
                      </span>
                    ) : tenant.has_connection ? (
                      <Freshness at={tenant.last_sync_at} />
                    ) : (
                      <span className="text-dim">no manager connection</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.silent_tenants.length > 0 && (
        <p className="mt-4 max-w-prose text-xs text-dim">
          A silent client is almost always an integration problem rather than a quiet
          week. Check the <span className="data">&lt;integration&gt;</span> block on
          their manager, the level floor, and that the console&rsquo;s address is in
          their egress allowlist.
        </p>
      )}
    </div>
  );
}
