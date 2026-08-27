import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { type AgentFilters, listAgents, syncAgents } from "@/api/agents";
import { Empty, ErrorNote, Freshness, Loading, relative } from "@/components/States";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

function StatusDot({ status }: { status: string | null }) {
  const colour =
    status === "active"
      ? "var(--sev-low)"
      : status === "disconnected"
        ? "var(--sev-crit)"
        : "var(--text-dim)";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className="inline-block h-2 w-2 rounded-full"
        style={{ background: colour }}
      />
      {status ?? "unknown"}
    </span>
  );
}

/** The fleet, read from our cache of each client's manager.
 *
 *  Everything here can be out of date and says so. The sync button is the only
 *  thing in the console that reaches a client's network on demand. */
export function Agents() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");

  const filters: AgentFilters = {
    status: params.get("status") ?? undefined,
    group: params.get("group") ?? undefined,
    q: params.get("q") ?? undefined,
  };

  const query = useQuery({
    queryKey: ["agents", filters],
    queryFn: () => listAgents(filters),
  });

  const sync = useMutation({
    mutationFn: () => syncAgents(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const agents = query.data?.items ?? [];
  const failures = sync.data?.filter((r) => !r.ok) ?? [];
  const oldest = agents.reduce<string | null>(
    (acc, a) => (acc === null || a.synced_at < acc ? a.synced_at : acc),
    null,
  );

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Agents</h1>
          <p className="mt-1 text-xs text-dim">
            A cache of each client&rsquo;s manager, not a live view.{" "}
            {oldest && <Freshness at={oldest} label="oldest synced" />}
          </p>
        </div>
        {user?.is_staff && (
          <button
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
            className="rounded border border-line px-3 py-1.5 text-sm transition hover:text-accent disabled:opacity-60"
          >
            {sync.isPending ? "Syncing…" : "Sync now"}
          </button>
        )}
      </div>

      {sync.isPending && (
        <p className="mt-3 text-sm text-dim">
          Connecting to each client&rsquo;s manager. This takes as long as the slowest
          one.
        </p>
      )}
      {failures.length > 0 && (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-line bg-ink-800 px-4 py-3 text-sm"
        >
          <p className="text-[color:var(--sev-high)]">
            {failures.length} client{failures.length > 1 ? "s" : ""} could not be
            reached. Their agents below are the last good copy.
          </p>
          <ul className="mt-2 space-y-1 text-xs text-dim">
            {failures.map((f) => (
              <li key={f.tenant_id}>
                <span className="data">{f.tenant_slug ?? f.tenant_id}</span> — {f.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setFilter("q", search);
          }}
        >
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search agent name"
            aria-label="Search agents"
            className={`${input} w-56`}
          />
        </form>

        <select
          value={params.get("status") ?? ""}
          onChange={(e) => setFilter("status", e.target.value)}
          aria-label="Agent status"
          className={input}
        >
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="disconnected">Disconnected</option>
          <option value="never_connected">Never connected</option>
          <option value="pending">Pending</option>
        </select>
      </div>

      {query.isLoading && <Loading what="agents" />}
      {query.error && (
        <ErrorNote
          error={query.error}
          fallback="Could not load agents."
          onRetry={() => void query.refetch()}
        />
      )}

      {!query.isLoading && !query.error && agents.length === 0 && (
        <Empty
          title="No agents cached."
          hint={
            user?.is_staff
              ? "Agents appear once a client has a Manager API connection configured and a sync has run. Add the connection under Clients, then press Sync now."
              : "Your manager has not been connected to the console yet."
          }
        />
      )}

      {agents.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[52rem] border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-ink-800">
              <tr className="border-b border-line text-left text-dim">
                <th className="px-3 py-1.5 text-xs font-medium">Status</th>
                <th className="px-3 py-1.5 text-xs font-medium">Agent</th>
                {user?.is_staff && <th className="px-3 py-1.5 text-xs font-medium">Client</th>}
                <th className="px-3 py-1.5 text-xs font-medium">Address</th>
                <th className="px-3 py-1.5 text-xs font-medium">OS</th>
                <th className="px-3 py-1.5 text-xs font-medium">Version</th>
                <th className="px-3 py-1.5 text-xs font-medium">Last keepalive</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => {
                const href = `/agents/${encodeURIComponent(agent.agent_id)}`;
                return (
                  <tr
                    key={`${agent.tenant_id}:${agent.agent_id}`}
                    onClick={() => navigate(href)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(href);
                      }
                    }}
                    tabIndex={0}
                    role="link"
                    aria-label={`Agent ${agent.name}`}
                    className="cursor-pointer border-b border-line outline-none transition last:border-b-0 hover:bg-ink-800 focus-visible:bg-ink-800 focus-visible:ring-1 focus-visible:ring-accent"
                    style={{
                      boxShadow: user?.is_staff
                        ? `inset 3px 0 0 ${agent.tenant_colour ?? "transparent"}`
                        : undefined,
                    }}
                  >
                    <td className="px-3 py-1.5">
                      <StatusDot status={agent.status} />
                    </td>
                    <td className="px-3 py-1.5">
                      {agent.name}
                      <span className="data ml-2 text-xs text-dim">
                        {agent.agent_id}
                      </span>
                    </td>
                    {user?.is_staff && (
                      <td className="px-3 py-1.5">
                        <TenantChip
                          name={agent.tenant_name}
                          colour={agent.tenant_colour}
                        />
                      </td>
                    )}
                    <td className="data px-3 py-1.5 text-xs text-dim">
                      {agent.ip ?? "—"}
                    </td>
                    <td className="px-3 py-1.5 text-xs text-dim">
                      {agent.os_name ?? agent.os_platform ?? "—"}
                    </td>
                    <td className="data px-3 py-1.5 text-xs text-dim">
                      {agent.version ?? "—"}
                    </td>
                    <td className="data px-3 py-1.5 text-xs text-dim">
                      {agent.last_keepalive ? relative(agent.last_keepalive) : "never"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
