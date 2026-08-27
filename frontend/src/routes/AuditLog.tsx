import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { listAudit } from "@/api/users";
import { Empty, ErrorNote, Loading } from "@/components/States";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

/** Actions worth arguing about later. On an MSSP that includes every SLA pause,
 *  because a paused clock cannot breach and someone will eventually ask why. */
const ACTIONS = [
  "incident.updated",
  "incident.bulk_updated",
  "incident.commented",
  "entity.notes_updated",
  "tenant.created",
  "tenant.updated",
  "tenant.secret_rotated",
  "agents.synced",
  "user.created",
  "user.updated",
  "user.password_reset",
];

function summarise(detail: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(detail)) {
    if (value === null || value === undefined) continue;
    if (typeof value === "object") {
      const nested = value as Record<string, unknown>;
      if ("from" in nested && "to" in nested) {
        parts.push(`${key}: ${String(nested.from)} → ${String(nested.to)}`);
        continue;
      }
      parts.push(`${key}: ${JSON.stringify(value)}`);
      continue;
    }
    parts.push(`${key}: ${String(value)}`);
  }
  return parts.join(" · ");
}

export function AuditLog() {
  const [params, setParams] = useSearchParams();
  const [target, setTarget] = useState(params.get("target_id") ?? "");

  const filters = {
    action: params.get("action") ?? undefined,
    target_id: params.get("target_id") ?? undefined,
  };

  const query = useInfiniteQuery({
    queryKey: ["audit", filters],
    queryFn: ({ pageParam }) => listAudit(filters, pageParam as number | undefined),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const entries = query.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-lg font-semibold">Audit log</h1>
      <p className="mt-1 max-w-prose text-xs text-dim">
        Append-only. Every entry joined the transaction that made the change, so a
        recorded action and the change it describes cannot disagree.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <select
          value={params.get("action") ?? ""}
          onChange={(e) => setFilter("action", e.target.value)}
          aria-label="Action"
          className={input}
        >
          <option value="">Any action</option>
          {ACTIONS.map((action) => (
            <option key={action} value={action}>
              {action}
            </option>
          ))}
        </select>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            setFilter("target_id", target.trim());
          }}
        >
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="Filter by target id"
            aria-label="Target id"
            className={`${input} data w-72`}
          />
        </form>
      </div>

      {query.isLoading && <Loading what="audit entries" />}
      {query.error && (
        <ErrorNote
          error={query.error}
          fallback="Could not load the audit log."
          onRetry={() => void query.refetch()}
        />
      )}

      {!query.isLoading && !query.error && entries.length === 0 && (
        <Empty
          title="Nothing recorded yet."
          hint="Entries appear as soon as somebody changes an incident, a client or a user."
        />
      )}

      {entries.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[48rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-dim">
                <th className="px-3 py-2 font-normal">When</th>
                <th className="px-3 py-2 font-normal">Who</th>
                <th className="px-3 py-2 font-normal">Action</th>
                <th className="px-3 py-2 font-normal">Detail</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} className="border-b border-line last:border-b-0">
                  <td className="data whitespace-nowrap px-3 py-2 text-xs text-dim">
                    {new Date(entry.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {entry.actor_name ?? (
                      <span className="text-dim">system</span>
                    )}
                  </td>
                  <td className="data px-3 py-2 text-xs">{entry.action}</td>
                  <td className="px-3 py-2 text-xs text-dim">
                    {summarise(entry.detail) || "—"}
                  </td>
                </tr>
              ))}
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
