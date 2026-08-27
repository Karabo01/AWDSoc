import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  type EntityFilters,
  type EntityType,
  listEntities,
} from "@/api/entities";
import { Empty, ErrorNote, Loading, relative } from "@/components/States";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

const TYPES: EntityType[] = ["ip", "user", "host", "hash"];

export function entityHref(type: string, value: string): string {
  return `/entities/${type}/${encodeURIComponent(value)}`;
}

/** The tenant-scoped index of everything we have observed.
 *
 *  Ordered by `last_seen` rather than by count on purpose: an analyst opening
 *  this page is asking "what is happening", not "what has happened most". */
export function Entities() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");

  const filters: EntityFilters = {
    type: (params.get("type") as EntityType) || undefined,
    q: params.get("q") ?? undefined,
    min_alerts: params.get("min_alerts") ? Number(params.get("min_alerts")) : undefined,
  };

  const query = useInfiniteQuery({
    queryKey: ["entities", filters],
    queryFn: ({ pageParam }) => listEntities(filters, pageParam as string | undefined),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const entities = query.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = Boolean(filters.q || filters.type || filters.min_alerts);

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Entities</h1>
        <span className="data text-xs text-dim">
          {entities.length}
          {query.hasNextPage ? "+" : ""} shown
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
            placeholder="Search address, user, host"
            aria-label="Search entities"
            className={`${input} w-64`}
          />
        </form>

        <select
          value={params.get("type") ?? ""}
          onChange={(e) => setFilter("type", e.target.value)}
          aria-label="Entity type"
          className={input}
        >
          <option value="">Any type</option>
          {TYPES.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>

        <select
          value={params.get("min_alerts") ?? ""}
          onChange={(e) => setFilter("min_alerts", e.target.value)}
          aria-label="Minimum alerts"
          className={input}
        >
          <option value="">Any volume</option>
          <option value="5">5+ alerts</option>
          <option value="25">25+ alerts</option>
          <option value="100">100+ alerts</option>
        </select>
      </div>

      {query.isLoading && <Loading what="entities" />}
      {query.error && (
        <ErrorNote
          error={query.error}
          fallback="Could not load entities."
          onRetry={() => void query.refetch()}
        />
      )}

      {!query.isLoading && !query.error && entities.length === 0 && (
        <Empty
          title={filtered ? "Nothing matches those filters." : "No entities yet."}
          hint={
            filtered
              ? "Entities are only created from alerts that have been normalised, so a very recent alert may not be indexed yet."
              : "An entity appears the first time an alert names an address, user, host or hash. Once alerts are arriving, this fills itself."
          }
        />
      )}

      {entities.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[46rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-dim">
                <th className="px-3 py-2 font-normal">Type</th>
                <th className="px-3 py-2 font-normal">Value</th>
                {user?.is_staff && <th className="px-3 py-2 font-normal">Client</th>}
                <th className="px-3 py-2 font-normal">Alerts</th>
                <th className="px-3 py-2 font-normal">First seen</th>
                <th className="px-3 py-2 font-normal">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {entities.map((entity) => {
                const href = entityHref(entity.type, entity.value);
                return (
                  <tr
                    key={entity.id}
                    onClick={() => navigate(href)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(href);
                      }
                    }}
                    tabIndex={0}
                    role="link"
                    aria-label={`${entity.type} ${entity.value}`}
                    className="cursor-pointer border-b border-line outline-none transition last:border-b-0 hover:bg-ink-800 focus-visible:bg-ink-800 focus-visible:ring-1 focus-visible:ring-accent"
                    style={{
                      boxShadow: user?.is_staff
                        ? `inset 3px 0 0 ${entity.tenant_colour ?? "transparent"}`
                        : undefined,
                    }}
                  >
                    <td className="px-3 py-2 text-xs text-dim">{entity.type}</td>
                    <td className="data px-3 py-2">
                      {entity.value}
                      {entity.has_notes && (
                        <span
                          className="ml-2 text-xs text-accent"
                          title="An analyst has left notes on this entity"
                        >
                          noted
                        </span>
                      )}
                    </td>
                    {user?.is_staff && (
                      <td className="px-3 py-2">
                        <TenantChip
                          name={entity.tenant_name}
                          colour={entity.tenant_colour}
                        />
                      </td>
                    )}
                    <td className="data px-3 py-2 text-xs text-dim">
                      {entity.alert_count.toLocaleString()}
                    </td>
                    <td className="data px-3 py-2 text-xs text-dim">
                      {relative(entity.first_seen)}
                    </td>
                    <td className="data px-3 py-2 text-xs text-dim">
                      {relative(entity.last_seen)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {query.hasNextPage && (
        <button
          onClick={() => void query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
          className="mt-4 rounded border border-line px-3 py-1.5 text-sm text-dim transition hover:text-text disabled:opacity-60"
        >
          {query.isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
