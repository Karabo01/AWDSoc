import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CircleSlash,
  PlayCircle,
  RefreshCw,
  UserPlus,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  type IncidentFilters,
  type IncidentSummary,
  type SortKey,
  bulkUpdate,
  listIncidents,
} from "@/api/incidents";
import {
  ColumnChooser,
  Command,
  CommandBar,
  CommandDivider,
} from "@/components/CommandBar";
import { GridHead, GridShell, SortTh, Th, gridCell } from "@/components/DataGrid";
import { IncidentPane } from "@/components/IncidentPane";
import { SeverityChip } from "@/components/SeverityChip";
import { SlaClock } from "@/components/SlaClock";
import { Empty, ErrorNote, Loading, relative } from "@/components/States";
import { StatusBadge } from "@/components/StatusBadge";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";
import { useIncidentStream } from "@/hooks/useIncidentStream";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-xs outline-none transition focus:border-accent";

const COLUMNS = [
  { key: "severity", label: "Level", locked: true },
  { key: "title", label: "Incident", locked: true },
  { key: "tenant", label: "Client" },
  { key: "status", label: "Status" },
  { key: "sla", label: "SLA" },
  { key: "alerts", label: "Alerts" },
  { key: "assignee", label: "Assignee" },
  { key: "last_seen", label: "Last seen" },
];

const HIDDEN_KEY = "awdsoc.incidents.columns";

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
  return (
    <span
      className="flex items-center gap-1.5 text-xs text-dim"
      title={
        state === "offline"
          ? "Reconnecting — the list still refreshes on its own"
          : "Live updates"
      }
    >
      <span
        aria-hidden
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: colour }}
      />
      {state === "live" ? "Live" : state === "connecting" ? "Connecting…" : "Reconnecting"}
    </span>
  );
}

export function Incidents() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState(0);
  const [active, setActive] = useState<IncidentSummary | null>(null);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  const [hidden, setHidden] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem(HIDDEN_KEY);
      return new Set(stored ? (JSON.parse(stored) as string[]) : []);
    } catch {
      return new Set();
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(HIDDEN_KEY, JSON.stringify([...hidden]));
    } catch {
      /* a private window is not a reason to lose the grid */
    }
  }, [hidden]);

  const stream = useIncidentStream(true);
  const canTriage = user?.role !== "client_viewer";
  const sort = (params.get("sort") as SortKey) ?? "last_seen";
  const order = (params.get("order") as "asc" | "desc") ?? "desc";

  const filters: IncidentFilters = {
    q: params.get("q") ?? undefined,
    severity_min: params.get("severity_min")
      ? Number(params.get("severity_min"))
      : undefined,
    assignee: params.get("assignee") ?? undefined,
    status: params.getAll("status").length ? params.getAll("status") : undefined,
    open_only: params.get("status") ? undefined : true,
    sort,
    order,
  };

  const query = useInfiniteQuery({
    queryKey: ["incidents", filters],
    queryFn: ({ pageParam }) => listIncidents(filters, pageParam as string | undefined),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // SSE is the primary signal; this is the fallback for when it is down.
    refetchInterval: stream.state === "live" ? 120_000 : 30_000,
  });

  const incidents = query.data?.pages.flatMap((page) => page.items) ?? [];

  const bulk = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      bulkUpdate({ incident_ids: [...selected], ...body }),
    onSuccess: (result) => {
      // Anything the server refused stays selected, so a partial failure is
      // visible and retryable rather than silently dropped.
      setSelected(new Set(result.skipped));
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setSelected(new Set());
    setCursor(0);
  }

  function onSort(key: string) {
    const next = new URLSearchParams(params);
    next.set("sort", key);
    // First click on a new column sorts descending — for severity and recency
    // that is the interesting end, and it saves a second click almost every time.
    next.set("order", sort === key && order === "desc" ? "asc" : "desc");
    setParams(next, { replace: true });
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
      if (event.key === "Escape") {
        setSelected(new Set());
        setActive(null);
        return;
      }
      if (incidents.length === 0) return;

      // Clamped here rather than trusting the filter handler, because a live
      // update can shrink the list too.
      const at = Math.min(cursor, incidents.length - 1);
      const focused = incidents[at];

      const move = (delta: number) => {
        event.preventDefault();
        const next = Math.min(Math.max(at + delta, 0), incidents.length - 1);
        setCursor(next);
        rowRefs.current[next]?.focus();
        // With the pane open, moving the cursor moves the pane — that is the
        // whole point of a preview pane over a modal.
        setActive((current) => (current ? incidents[next] : current));
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
          return setActive(focused);
        case "o":
          event.preventDefault();
          return navigate(caseHref(focused));
        case "a":
          if (selected.size === 0) return;
          event.preventDefault();
          return bulk.mutate({ assign_to_me: true });
        case "r":
          if (!canTriage) return;
          event.preventDefault();
          // Acts on the selection if there is one, otherwise on the focused row,
          // which is what an analyst working down a list means by "resolve".
          return bulk.mutate(
            selected.size > 0
              ? { status: "resolved" }
              : { status: "resolved", incident_ids: [focused.id] },
          );
        default:
          return;
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [incidents, cursor, selected, toggle, navigate, bulk, canTriage]);

  const allSelected = incidents.length > 0 && selected.size === incidents.length;
  const none = selected.size === 0;
  const shows = (key: string) => !hidden.has(key);

  return (
    <div className="flex h-full min-h-0 gap-4">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-base font-semibold">Incidents</h1>
          <div className="flex items-center gap-3">
            <LiveDot state={stream.state} />
            <span className="data text-xs text-dim">
              {incidents.length}
              {query.hasNextPage ? "+" : ""} shown
            </span>
          </div>
        </div>

        <div className="mt-3">
          <CommandBar>
            <Command
              icon={RefreshCw}
              label="Refresh"
              busy={query.isFetching}
              onClick={() => void query.refetch()}
            />
            {canTriage && (
              <>
                <CommandDivider />
                <Command
                  icon={UserPlus}
                  label="Assign to me"
                  disabled={none}
                  busy={bulk.isPending}
                  onClick={() => bulk.mutate({ assign_to_me: true })}
                />
                <Command
                  icon={PlayCircle}
                  label="Start work"
                  disabled={none}
                  busy={bulk.isPending}
                  onClick={() => bulk.mutate({ status: "active" })}
                />
                <Command
                  icon={CheckCircle2}
                  label="Resolve"
                  disabled={none}
                  busy={bulk.isPending}
                  onClick={() => bulk.mutate({ status: "resolved" })}
                />
                <Command
                  icon={CircleSlash}
                  label="False positive"
                  disabled={none}
                  busy={bulk.isPending}
                  onClick={() => bulk.mutate({ status: "false_positive" })}
                />
              </>
            )}
            <div className="ml-auto flex items-center gap-1">
              {selected.size > 0 && (
                <span className="px-2 text-xs text-accent">{selected.size} selected</span>
              )}
              <ColumnChooser
                columns={COLUMNS}
                hidden={hidden}
                onToggle={(key) =>
                  setHidden((current) => {
                    const next = new Set(current);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                  })
                }
              />
            </div>
          </CommandBar>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setParam("q", search);
            }}
          >
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search title"
              aria-label="Search incidents"
              className={`${input} w-52`}
            />
          </form>

          <select
            value={params.get("status") ?? ""}
            onChange={(e) => setParam("status", e.target.value)}
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
            onChange={(e) => setParam("severity_min", e.target.value)}
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
            onChange={(e) => setParam("assignee", e.target.value)}
            aria-label="Assignee"
            className={input}
          >
            <option value="">Anyone</option>
            <option value="me">Assigned to me</option>
            <option value="unassigned">Unassigned</option>
          </select>
        </div>

        {stream.pending > 0 && (
          <button
            onClick={stream.merge}
            className="mt-3 self-start rounded-full border border-accent/50 bg-ink-800 px-3 py-1 text-xs text-accent transition hover:brightness-125"
          >
            {stream.pending} new incident{stream.pending > 1 ? "s" : ""} — click to show
          </button>
        )}

        {bulk.data?.reason && (
          <p className="mt-2 text-xs text-[color:var(--sev-med)]">{bulk.data.reason}</p>
        )}
        {bulk.error && (
          <ErrorNote error={bulk.error} fallback="Could not apply that change." />
        )}

        {query.isLoading && <Loading what="incidents" />}
        {query.error && (
          <ErrorNote
            error={query.error}
            fallback="Could not load incidents."
            onRetry={() => void query.refetch()}
          />
        )}

        {!query.isLoading && !query.error && incidents.length === 0 && (
          <Empty
            title="No open incidents."
            hint="Alerts below level 7 aren't ingested — change the threshold in this client's integration settings if you're expecting more."
          />
        )}

        {incidents.length > 0 && (
          <div className="mt-3 min-h-0 flex-1">
            <GridShell>
              <table className="w-full min-w-[46rem] border-collapse text-sm">
                <GridHead>
                  {canTriage && (
                    <Th className="w-8">
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
                    </Th>
                  )}
                  <SortTh
                    label="Level"
                    sortKey="severity"
                    active={sort}
                    order={order}
                    onSort={onSort}
                  />
                  <SortTh
                    label="Incident"
                    sortKey="number"
                    active={sort}
                    order={order}
                    onSort={onSort}
                  />
                  {user?.is_staff && shows("tenant") && <Th>Client</Th>}
                  {shows("status") && <Th>Status</Th>}
                  {shows("sla") && <Th>SLA</Th>}
                  {shows("alerts") && (
                    <SortTh
                      label="Alerts"
                      sortKey="alert_count"
                      active={sort}
                      order={order}
                      onSort={onSort}
                    />
                  )}
                  {shows("assignee") && <Th>Assignee</Th>}
                  {shows("last_seen") && (
                    <SortTh
                      label="Last seen"
                      sortKey="last_seen"
                      active={sort}
                      order={order}
                      onSort={onSort}
                    />
                  )}
                </GridHead>
                <tbody>
                  {incidents.map((incident, index) => {
                    const isActive = active?.id === incident.id;
                    return (
                      <tr
                        key={incident.id}
                        ref={(node) => {
                          rowRefs.current[index] = node;
                        }}
                        onClick={() => {
                          setCursor(index);
                          setActive(incident);
                        }}
                        onFocus={() => setCursor(index)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setActive(incident);
                          }
                        }}
                        tabIndex={0}
                        aria-label={`Incident ${incident.number}: ${incident.title}`}
                        aria-selected={isActive}
                        className={`cursor-pointer border-b border-line outline-none transition last:border-b-0 hover:bg-ink-800 focus-visible:bg-ink-800 focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-accent ${
                          isActive
                            ? "bg-ink-700"
                            : selected.has(incident.id)
                              ? "bg-ink-800"
                              : ""
                        }`}
                        style={{
                          boxShadow: user?.is_staff
                            ? `inset 3px 0 0 ${incident.tenant_colour ?? "transparent"}`
                            : undefined,
                        }}
                      >
                        {canTriage && (
                          <td className={gridCell} onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={selected.has(incident.id)}
                              onChange={() => toggle(incident.id)}
                              aria-label={`Select incident ${incident.number}`}
                            />
                          </td>
                        )}
                        <td className={gridCell}>
                          <SeverityChip level={incident.severity} />
                        </td>
                        <td className={gridCell}>
                          {/* Still a real link, so middle-click and open-in-new-tab
                              reach the full case rather than the pane. */}
                          <Link
                            to={caseHref(incident)}
                            onClick={(e) => e.stopPropagation()}
                            className="transition hover:text-accent"
                          >
                            {incident.title}
                          </Link>
                          <span className="data ml-2 text-xs text-dim">
                            #{incident.number}
                          </span>
                        </td>
                        {user?.is_staff && shows("tenant") && (
                          <td className={gridCell}>
                            <TenantChip
                              name={incident.tenant_name}
                              colour={incident.tenant_colour}
                            />
                          </td>
                        )}
                        {shows("status") && (
                          <td className={gridCell}>
                            <StatusBadge status={incident.status} />
                          </td>
                        )}
                        {shows("sla") && (
                          <td className={gridCell}>
                            <SlaClock incident={incident} />
                          </td>
                        )}
                        {shows("alerts") && (
                          <td className={`${gridCell} data text-xs text-dim`}>
                            {incident.alert_count}
                          </td>
                        )}
                        {shows("assignee") && (
                          <td className={`${gridCell} text-xs text-dim`}>
                            {incident.assignee_name ?? "—"}
                          </td>
                        )}
                        {shows("last_seen") && (
                          <td className={`${gridCell} data text-xs text-dim`}>
                            {relative(incident.last_seen)}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </GridShell>
          </div>
        )}

        {query.hasNextPage && (
          <button
            onClick={() => void query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
            className="mt-3 self-start rounded border border-line px-3 py-1.5 text-xs text-dim transition hover:text-text disabled:opacity-60"
          >
            {query.isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        )}

        {incidents.length > 0 && (
          <p className="mt-3 text-xs text-dim">
            <span className="data">j</span>/<span className="data">k</span> move ·{" "}
            <span className="data">Enter</span> preview · <span className="data">o</span>{" "}
            open · <span className="data">x</span> select ·{" "}
            <span className="data">a</span> assign · <span className="data">r</span>{" "}
            resolve · <span className="data">Esc</span> close
          </p>
        )}
      </div>

      {active && (
        <IncidentPane
          key={active.id}
          incident={active}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}
