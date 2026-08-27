import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  type IncidentFilters,
  bulkUpdate,
  listIncidents,
} from "@/api/incidents";
import { SeverityChip } from "@/components/SeverityChip";
import { SlaClock } from "@/components/SlaClock";
import { Empty, ErrorNote, Loading, relative } from "@/components/States";
import { StatusBadge } from "@/components/StatusBadge";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";
import { useIncidentStream } from "@/hooks/useIncidentStream";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

/** A case is addressed by client and number, not by UUID, so the URL is
 *  something an analyst can read out loud. */
function caseHref(incident: { tenant_slug: string | null; number: number }): string {
  return `/incidents/${incident.tenant_slug ?? "-"}/${incident.number}`;
}

function LiveDot({ state }: { state: "connecting" | "live" | "offline" }) {
  const colour =
    state === "live"
      ? "var(--sev-low)"
      : state === "connecting"
        ? "var(--text-dim)"
        : "var(--sev-med)";
  const label =
    state === "live"
      ? "Live"
      : state === "connecting"
        ? "Connecting"
        : "Reconnecting — the list still refreshes on its own";
  return (
    <span className="flex items-center gap-1.5 text-xs text-dim" title={label}>
      <span
        aria-hidden
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: colour }}
      />
      {state === "live" ? "Live" : state === "connecting" ? "Connecting…" : "Reconnecting"}
    </span>
  );
}

/** The cross-tenant queue. One component, two audiences: a staff token gets the
 *  tenant chip, a client token gets the same list without it.
 *
 *  Keyboard-first, because triaging forty cases with a mouse is the slow way:
 *  j/k move, x selects, Enter opens, a assigns, Escape clears. The shortcuts are
 *  listed on the page rather than hidden behind a help modal nobody opens. */
export function Incidents() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState(0);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  const stream = useIncidentStream(true);

  const filters: IncidentFilters = {
    q: params.get("q") ?? undefined,
    severity_min: params.get("severity_min")
      ? Number(params.get("severity_min"))
      : undefined,
    assignee: params.get("assignee") ?? undefined,
    status: params.getAll("status").length ? params.getAll("status") : undefined,
    open_only: params.get("status") ? undefined : true,
  };

  const { data, error, isLoading, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ["incidents", filters],
      queryFn: ({ pageParam }) =>
        listIncidents(filters, pageParam as string | undefined),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last) => last.next_cursor ?? undefined,
      // The SSE stream is the primary signal; this is the fallback for when it
      // is down, so it can be far slower than the 30s M5 shipped with.
      refetchInterval: stream.state === "live" ? 120_000 : 30_000,
    });

  const incidents = data?.pages.flatMap((page) => page.items) ?? [];

  const bulk = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      bulkUpdate({ incident_ids: [...selected], ...body }),
    onSuccess: (result) => {
      // Keep anything the server refused selected, so a partial failure is
      // visible and retryable rather than silently dropped.
      setSelected(new Set(result.skipped));
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setSelected(new Set());
    setCursor(0);
  }

  const toggle = useCallback((id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Shortcuts are ignored while a text field has focus — otherwise typing "a"
  // into the search box would reassign the queue.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (incidents.length === 0) return;

      // A narrowing filter can leave the cursor past the end of the new list.
      // Clamping here rather than trusting `setFilter` covers the other way a
      // list shrinks too: a live update removing a row that no longer matches.
      const at = Math.min(cursor, incidents.length - 1);
      const focused = incidents[at];

      const move = (delta: number) => {
        event.preventDefault();
        setCursor(() => {
          const next = Math.min(Math.max(at + delta, 0), incidents.length - 1);
          rowRefs.current[next]?.focus();
          return next;
        });
      };

      switch (event.key) {
        case "j":
        case "ArrowDown":
          return move(1);
        case "k":
        case "ArrowUp":
          return move(-1);
        case "x":
          event.preventDefault();
          return toggle(focused.id);
        case "Enter":
          event.preventDefault();
          return navigate(caseHref(focused));
        case "a":
          if (selected.size === 0) return;
          event.preventDefault();
          return bulk.mutate({ assign_to_me: true });
        case "Escape":
          return setSelected(new Set());
        default:
          return;
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [incidents, cursor, selected, toggle, navigate, bulk]);

  const canTriage = user?.role !== "client_viewer";
  const allSelected = incidents.length > 0 && selected.size === incidents.length;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Incidents</h1>
        <div className="flex items-center gap-3">
          <LiveDot state={stream.state} />
          <span className="data text-xs text-dim">
            {incidents.length}
            {hasNextPage ? "+" : ""} shown
          </span>
        </div>
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
            aria-label="Search incidents"
            className={`${input} w-56`}
          />
        </form>

        <select
          value={params.get("status") ?? ""}
          onChange={(e) => setFilter("status", e.target.value)}
          aria-label="Status"
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
          aria-label="Minimum level"
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
          aria-label="Assignee"
          className={input}
        >
          <option value="">Anyone</option>
          <option value="me">Assigned to me</option>
          <option value="unassigned">Unassigned</option>
        </select>
      </div>

      {/* Bulk bar. Only appears with a selection, so it never occupies space
          during ordinary reading. */}
      {canTriage && selected.size > 0 && (
        <div className="sticky top-0 z-10 mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-accent/40 bg-ink-800 px-3 py-2">
          <span className="text-sm">
            {selected.size} selected
          </span>
          <button
            onClick={() => bulk.mutate({ assign_to_me: true })}
            disabled={bulk.isPending}
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-60"
          >
            Assign to me
          </button>
          <button
            onClick={() => bulk.mutate({ status: "active" })}
            disabled={bulk.isPending}
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-60"
          >
            Start work
          </button>
          <button
            onClick={() => bulk.mutate({ status: "resolved" })}
            disabled={bulk.isPending}
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-60"
          >
            Resolve
          </button>
          <button
            onClick={() => bulk.mutate({ status: "false_positive" })}
            disabled={bulk.isPending}
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-60"
          >
            False positive
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-auto text-xs text-dim underline transition hover:text-text"
          >
            Clear
          </button>
        </div>
      )}

      {bulk.data?.reason && (
        <p className="mt-2 text-xs text-[color:var(--sev-med)]">{bulk.data.reason}</p>
      )}
      {bulk.error && (
        <ErrorNote error={bulk.error} fallback="Could not apply that change." />
      )}

      {isLoading && <Loading what="incidents" />}
      {error && (
        <ErrorNote
          error={error}
          fallback="Could not load incidents."
          onRetry={() => void refetch()}
        />
      )}

      {!isLoading && !error && incidents.length === 0 && (
        <Empty
          title="No open incidents."
          hint="Alerts below level 7 aren't ingested — change the threshold in this client's integration settings if you're expecting more."
        />
      )}

      {incidents.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[58rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-dim">
                {canTriage && (
                  <th className="w-8 px-3 py-2">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      aria-label="Select all shown"
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? new Set(incidents.map((i) => i.id))
                            : new Set(),
                        )
                      }
                    />
                  </th>
                )}
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
              {incidents.map((incident, index) => (
                <tr
                  key={incident.id}
                  ref={(node) => {
                    rowRefs.current[index] = node;
                  }}
                  // The whole row opens the case. An analyst working a queue
                  // aims at the row, not at the four characters of the title.
                  onClick={() => navigate(caseHref(incident))}
                  onFocus={() => setCursor(index)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      navigate(caseHref(incident));
                    }
                  }}
                  tabIndex={0}
                  role="link"
                  aria-label={`Incident ${incident.number}: ${incident.title}`}
                  className={`cursor-pointer border-b border-line outline-none transition last:border-b-0 hover:bg-ink-800 focus-visible:bg-ink-800 focus-visible:ring-1 focus-visible:ring-accent ${
                    selected.has(incident.id) ? "bg-ink-700" : ""
                  }`}
                  style={{
                    boxShadow: user?.is_staff
                      ? `inset 3px 0 0 ${incident.tenant_colour ?? "transparent"}`
                      : undefined,
                  }}
                >
                  {canTriage && (
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(incident.id)}
                        onChange={() => toggle(incident.id)}
                        aria-label={`Select incident ${incident.number}`}
                      />
                    </td>
                  )}
                  <td className="px-3 py-2">
                    <SeverityChip level={incident.severity} />
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      to={caseHref(incident)}
                      onClick={(e) => e.stopPropagation()}
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

      {incidents.length > 0 && (
        <p className="mt-4 text-xs text-dim">
          <span className="data">j</span>/<span className="data">k</span> move ·{" "}
          <span className="data">x</span> select · <span className="data">Enter</span>{" "}
          open · <span className="data">a</span> assign to me ·{" "}
          <span className="data">Esc</span> clear
        </p>
      )}
    </div>
  );
}
