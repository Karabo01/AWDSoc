import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { agentAlerts, getAgent } from "@/api/agents";
import { SeverityChip } from "@/components/SeverityChip";
import { Empty, ErrorNote, Freshness, Loading, relative } from "@/components/States";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

function Field({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <dt className="text-xs text-dim">{label}</dt>
      <dd className="data mt-0.5 text-sm">{value ?? "—"}</dd>
    </div>
  );
}

export function AgentDetail() {
  const { agentId: raw } = useParams<{ agentId: string }>();
  const agentId = decodeURIComponent(raw ?? "");
  const { user } = useAuth();

  const agent = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => getAgent(agentId),
  });

  const alerts = useQuery({
    queryKey: ["agent-alerts", agentId],
    queryFn: () => agentAlerts(agentId),
    enabled: Boolean(agent.data),
  });

  if (agent.isLoading) return <Loading what="agent" />;
  if (agent.error)
    return (
      <ErrorNote
        error={agent.error}
        fallback="Could not load that agent."
        onRetry={() => void agent.refetch()}
      />
    );
  if (!agent.data) return null;

  const data = agent.data;

  return (
    <div className="mx-auto max-w-5xl">
      <Link to="/agents" className="text-sm text-dim transition hover:text-text">
        ← Agents
      </Link>

      <div className="mt-2 flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold">{data.name}</h1>
        <span className="data text-sm text-dim">{data.agent_id}</span>
        {user?.is_staff && (
          <TenantChip name={data.tenant_name} colour={data.tenant_colour} />
        )}
        <Freshness at={data.synced_at} />
      </div>

      {data.misgrouped_with && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-[color:var(--sev-crit)] bg-ink-800 px-4 py-3 text-sm"
        >
          <p className="font-medium text-[color:var(--sev-crit)]">
            This agent is visible to more than one client.
          </p>
          <p className="mt-1 text-dim">
            Agent IDs are unique within a manager, so the same ID under{" "}
            <span className="data">{data.misgrouped_with.join(", ")}</span> means their
            agent groups overlap. Until the groups are corrected on the manager, one of
            these clients is receiving the other&rsquo;s alerts. The console cannot fix
            this from here — the <span className="data">&lt;group&gt;</span> filter in{" "}
            <span className="data">ossec.conf</span> decides it.
          </p>
        </div>
      )}

      <dl className="mt-6 grid gap-4 rounded-lg border border-line bg-ink-800 p-4 sm:grid-cols-3">
        <Field label="Status" value={data.status} />
        <Field label="Address" value={data.ip} />
        <Field label="Version" value={data.version} />
        <Field label="Operating system" value={data.os_name ?? data.os_platform} />
        <Field
          label="Last keepalive"
          value={data.last_keepalive ? relative(data.last_keepalive) : "never"}
        />
        <Field label="Groups" value={data.groups.join(", ") || "—"} />
      </dl>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-line bg-ink-800 px-3 py-2">
          <p className="text-xs text-dim">Alerts, last 24h</p>
          <p className="data mt-1 text-lg">{data.alerts_24h.toLocaleString()}</p>
        </div>
        <div className="rounded-lg border border-line bg-ink-800 px-3 py-2">
          <p className="text-xs text-dim">Open incidents</p>
          <p className="data mt-1 text-lg">{data.open_incidents}</p>
        </div>
        <div className="rounded-lg border border-line bg-ink-800 px-3 py-2">
          <p className="text-xs text-dim">Last alert</p>
          <p className="data mt-1 text-lg">
            {data.last_alert_at ? relative(data.last_alert_at) : "—"}
          </p>
        </div>
      </div>

      {data.status === "active" && data.alerts_24h === 0 && (
        <p className="mt-4 text-sm text-dim">
          This agent is connected but has sent nothing in 24 hours. That is normal for a
          quiet host — alerts below the client&rsquo;s level floor never leave their
          manager.
        </p>
      )}

      <section className="mt-8">
        <h2 className="text-sm font-medium">Recent alerts</h2>
        {alerts.isLoading && <Loading what="alerts" />}
        {alerts.data?.items.length === 0 && (
          <Empty
            title="No alerts from this agent in the retained window."
            hint="Either the host is quiet, or nothing it produced reached the client's level floor."
          />
        )}
        {alerts.data && alerts.data.items.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[40rem] border-collapse text-sm">
              <tbody>
                {alerts.data.items.map((alert) => (
                  <tr key={alert.id} className="border-b border-line last:border-b-0">
                    <td className="px-3 py-2">
                      <SeverityChip level={alert.rule_level} />
                    </td>
                    <td className="px-3 py-2">
                      <Link
                        to={`/alerts/${alert.id}`}
                        className="transition hover:text-accent"
                      >
                        {alert.rule_desc}
                      </Link>
                      <span className="data ml-2 text-xs text-dim">{alert.rule_id}</span>
                    </td>
                    <td className="data px-3 py-2 text-xs text-dim">
                      {relative(alert.timestamp)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Link
          to={`/alerts?agent_id=${encodeURIComponent(agentId)}`}
          className="mt-3 inline-block text-sm text-dim underline transition hover:text-text"
        >
          See all alerts from this agent
        </Link>
      </section>
    </div>
  );
}
