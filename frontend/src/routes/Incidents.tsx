import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { type IncidentFilters, listIncidents } from "@/api/incidents";
import { SeverityChip } from "@/components/SeverityChip";
import { SlaClock } from "@/components/SlaClock";
import { StatusBadge } from "@/components/StatusBadge";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

function relative(value: string): string {
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** The cross-tenant queue. One component, two audiences: a staff token gets the
 *  tenant chip, a client token gets the same list without it. */
export function Incidents() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");

  const filters: IncidentFilters = {
    q: params.get("q") ?? undefined,
    severity_min: params.get("severity_min")
      ? Number(params.get("severity_min"))
      : undefined,
    assignee: params.get("assignee") ?? undefined,
    status: params.getAll("status").length ? params.getAll("status") : undefined,
    open_only: params.get("status") ? undefined : true,
  };

  const { data, error, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ["incidents", filters],
      queryFn: ({ pageParam }) =>
        listIncidents(filters, pageParam as string | undefined),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last) => last.next_cursor ?? undefined,
      refetchInterval: 30_000,
    });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const incidents = data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Incidents</h1>
        <span className="data text-xs text-dim">
          {incidents.length}
          {hasNextPage ? "+" : ""} shown
        </span>
      </div>

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
            placeholder="Search title"
            className={`${input} w-56`}
          />
        </form>

        <select
          value={params.get("status") ?? ""}
          onChange={(e) => setFilter("status", e.target.value)}
          className={input}
        >
          <option value="">Open</option>
          <option value="new">New</option>
          <option value="active">Active</option>
          <option value="pending">Awaiting client</option>
          <option value="resolved">Resolved</option>
          <option value="false_positive">False positive</option>
        </select>

        <select
          value={params.get("severity_min") ?? ""}
          onChange={(e) => setFilter("severity_min", e.target.value)}
          className={input}
        >
          <option value="">Any level</option>
          <option value="7">Level 7+</option>
          <option value="10">Level 10+</option>
          <option value="13">Level 13+</option>
        </select>

        <select
          value={params.get("assignee") ?? ""}
          onChange={(e) => setFilter("assignee", e.target.value)}
          className={input}
        >
          <option value="">Anyone</option>
          <option value="me">Assigned to me</option>
          <option value="unassigned">Unassigned</option>
        </select>
      </div>

      {isLoading && <p className="mt-6 text-sm text-dim">Loading incidents…</p>}

      {error && (
        <p className="mt-6 text-sm text-[color:var(--sev-crit)]">
          {error instanceof ApiError ? error.message : "Could not load incidents."}
        </p>
      )}

      {!isLoading && incidents.length === 0 && (
        <p className="mt-6 text-sm text-dim">
          No open incidents. Alerts below level 7 aren&rsquo;t ingested — change the
          threshold in this client&rsquo;s integration settings if you&rsquo;re expecting
          more.
        </p>
      )}

      {incidents.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[58rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-dim">
                <th className="px-3 py-2 font-normal">Level</th>
                <th className="px-3 py-2 font-normal">Incident</th>
                {user?.is_staff && <th className="px-3 py-2 font-normal">Client</th>}
                <th className="px-3 py-2 font-normal">Status</th>
                <th className="px-3 py-2 font-normal">SLA</th>
                <th className="px-3 py-2 font-normal">Alerts</th>
                <th className="px-3 py-2 font-normal">Assignee</th>
                <th className="px-3 py-2 font-normal">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((incident) => (
                <tr
                  key={incident.id}
                  className="border-b border-line transition last:border-b-0 hover:bg-ink-800"
                  style={{
                    boxShadow: user?.is_staff
                      ? `inset 3px 0 0 ${incident.tenant_colour ?? "transparent"}`
                      : undefined,
                  }}
                >
                  <td className="px-3 py-2">
                    <SeverityChip level={incident.severity} />
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      to={`/incidents/${incident.tenant_slug}/${incident.number}`}
                      className="transition hover:text-accent"
                    >
                      {incident.title}
                    </Link>
                    <span className="data ml-2 text-xs text-dim">#{incident.number}</span>
                  </td>
                  {user?.is_staff && (
                    <td className="px-3 py-2">
                      <TenantChip
                        name={incident.tenant_name}
                        colour={incident.tenant_colour}
                      />
                    </td>
                  )}
                  <td className="px-3 py-2">
                    <StatusBadge status={incident.status} />
                  </td>
                  <td className="px-3 py-2">
                    <SlaClock incident={incident} />
                  </td>
                  <td className="data px-3 py-2 text-xs text-dim">
                    {incident.alert_count}
                  </td>
                  <td className="px-3 py-2 text-xs text-dim">
                    {incident.assignee_name ?? "—"}
                  </td>
                  <td className="data px-3 py-2 text-xs text-dim">
                    {relative(incident.last_seen)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hasNextPage && (
        <button
          onClick={() => void fetchNextPage()}
          disabled={isFetchingNextPage}
          className="mt-4 rounded border border-line px-3 py-1.5 text-sm text-dim transition hover:text-text disabled:opacity-60"
        >
          {isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
