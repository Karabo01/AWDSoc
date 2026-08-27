import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { type AlertFilters, type EntityType, listAlerts } from "@/api/alerts";
import { SeverityChip } from "@/components/SeverityChip";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

function timestamp(value: string) {
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function Alerts() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");

  const filters: AlertFilters = {
    q: params.get("q") ?? undefined,
    severity_min: params.get("severity_min")
      ? Number(params.get("severity_min"))
      : undefined,
    rule_id: params.get("rule_id") ? Number(params.get("rule_id")) : undefined,
    entity_type: (params.get("entity_type") as EntityType) ?? undefined,
    entity_value: params.get("entity_value") ?? undefined,
    map_version: params.get("map_version")
      ? Number(params.get("map_version"))
      : undefined,
  };

  const { data, error, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ["alerts", filters],
      queryFn: ({ pageParam }) => listAlerts(filters, pageParam as string | undefined),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last) => last.next_cursor ?? undefined,
    });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const alerts = data?.pages.flatMap((page) => page.items) ?? [];
  const pivot = filters.entity_type && filters.entity_value;

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold">Alerts</h1>

      {pivot && (
        <p className="mt-2 flex items-center gap-2 text-sm text-dim">
          Pivoting on{" "}
          <span className="data rounded bg-ink-700 px-1.5 py-0.5 text-text">
            {filters.entity_type}:{filters.entity_value}
          </span>
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("entity_type");
              next.delete("entity_value");
              setParams(next, { replace: true });
            }}
            className="text-dim underline transition hover:text-text"
          >
            Clear
          </button>
        </p>
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
            placeholder="Search rule description"
            className={`${input} w-64`}
          />
        </form>

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
          value={params.get("map_version") ?? ""}
          onChange={(e) => setFilter("map_version", e.target.value)}
          className={input}
        >
          <option value="">Any mapping</option>
          <option value="-1">Failed to normalise</option>
          <option value="0">Not yet normalised</option>
        </select>
      </div>

      {isLoading && <p className="mt-6 text-sm text-dim">Loading alerts…</p>}

      {error && (
        <p className="mt-6 text-sm text-[color:var(--sev-crit)]">
          {error instanceof ApiError ? error.message : "Could not load alerts."}
        </p>
      )}

      {!isLoading && alerts.length === 0 && (
        <p className="mt-6 text-sm text-dim">
          No alerts match. Alerts below each client&rsquo;s floor are never sent — change
          the threshold in their integration settings if you expected more.
        </p>
      )}

      {alerts.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[52rem] border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-ink-800">
              <tr className="border-b border-line text-left text-dim">
                <th className="px-3 py-1.5 text-xs font-medium">Level</th>
                <th className="px-3 py-1.5 text-xs font-medium">Time</th>
                {user?.is_staff && <th className="px-3 py-1.5 text-xs font-medium">Client</th>}
                <th className="px-3 py-1.5 text-xs font-medium">Rule</th>
                <th className="px-3 py-1.5 text-xs font-medium">Agent</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => (
                <tr
                  key={alert.id}
                  className="border-b border-line transition last:border-b-0 hover:bg-ink-800"
                  style={{
                    boxShadow: user?.is_staff
                      ? `inset 3px 0 0 ${alert.tenant_colour ?? "transparent"}`
                      : undefined,
                  }}
                >
                  <td className="px-3 py-1.5">
                    <SeverityChip level={alert.rule_level} />
                  </td>
                  <td className="data px-3 py-1.5 text-xs text-dim">
                    {timestamp(alert.timestamp)}
                  </td>
                  {user?.is_staff && (
                    <td className="px-3 py-1.5">
                      <TenantChip name={alert.tenant_name} colour={alert.tenant_colour} />
                    </td>
                  )}
                  <td className="px-3 py-1.5">
                    <Link
                      to={`/alerts/${alert.id}`}
                      className="transition hover:text-accent"
                    >
                      {alert.rule_desc}
                    </Link>
                    <span className="data ml-2 text-xs text-dim">{alert.rule_id}</span>
                    {alert.map_version < 0 && (
                      <span className="ml-2 text-xs text-[color:var(--sev-high)]">
                        not normalised
                      </span>
                    )}
                  </td>
                  <td className="data px-3 py-1.5 text-xs text-dim">
                    {alert.agent_name ?? "—"}
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
