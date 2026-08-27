import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { Link } from "react-router-dom";

import {
  type IncidentSummary,
  getIncidentByNumber,
  incidentEntities,
  patchIncident,
} from "@/api/incidents";
import { SeverityChip } from "@/components/SeverityChip";
import { SlaClock } from "@/components/SlaClock";
import { ErrorNote, relative } from "@/components/States";
import { StatusBadge } from "@/components/StatusBadge";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 py-1.5">
      <span className="w-24 shrink-0 text-xs text-dim">{label}</span>
      <span className="min-w-0 flex-1 text-sm">{children}</span>
    </div>
  );
}

/** The triage pane.
 *
 *  Deliberately not the whole case view. It answers "do I need to open this?"
 *  and carries the four actions worth taking without opening it. The full page
 *  keeps the timeline, the alert list and the comment thread — and keeps its own
 *  URL, because a case address an analyst can read out loud is worth more than
 *  a pane that has swallowed it.
 *
 *  The queue stays mounted behind this, so filters, scroll position and the
 *  keyboard cursor all survive reading a case. That is the whole point. */
export function IncidentPane({
  incident,
  onClose,
}: {
  incident: IncidentSummary;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const href = `/incidents/${incident.tenant_slug ?? "-"}/${incident.number}`;

  // The summary from the list is enough to render immediately; the detail fills
  // in the rule breakdown behind it without a spinner over the whole pane.
  const detail = useQuery({
    queryKey: ["incident", incident.tenant_slug, incident.number],
    queryFn: () => getIncidentByNumber(incident.tenant_slug ?? "-", incident.number),
    enabled: Boolean(incident.tenant_slug),
  });

  const entities = useQuery({
    queryKey: ["incident-entities", incident.id],
    queryFn: () => incidentEntities(incident.id),
  });

  const act = useMutation({
    mutationFn: (body: Record<string, unknown>) => patchIncident(incident.id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void queryClient.invalidateQueries({ queryKey: ["incident"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const canTriage = user?.role !== "client_viewer";
  const rules = detail.data?.rule_summary ?? {};

  return (
    <aside
      aria-label={`Incident ${incident.number}`}
      className="flex h-full min-h-0 w-full flex-col overflow-y-auto border-line bg-ink-800 lg:w-[26rem] lg:shrink-0 lg:border-l"
    >
      <div className="sticky top-0 z-10 flex items-start gap-2 border-b border-line bg-ink-800 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <SeverityChip level={incident.severity} />
            <StatusBadge status={incident.status} />
            <span className="data text-xs text-dim">#{incident.number}</span>
          </div>
          <h2 className="mt-1.5 text-sm font-medium leading-snug">{incident.title}</h2>
        </div>
        <button
          onClick={onClose}
          aria-label="Close details"
          className="rounded p-1 text-dim transition hover:bg-ink-700 hover:text-text"
        >
          <X size={16} />
        </button>
      </div>

      {canTriage && (
        <div className="flex flex-wrap gap-1.5 border-b border-line px-4 py-2.5">
          <button
            onClick={() => act.mutate({ assign_to_me: true })}
            disabled={act.isPending || incident.assignee_id === user?.id}
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-40"
          >
            Assign to me
          </button>
          <button
            onClick={() => act.mutate({ status: "active" })}
            disabled={act.isPending || incident.status === "active"}
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-40"
          >
            Start work
          </button>
          <button
            onClick={() => act.mutate({ status: "pending" })}
            disabled={act.isPending || incident.status === "pending"}
            title="Stops the SLA clock"
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-40"
          >
            Wait on client
          </button>
          <button
            onClick={() => act.mutate({ status: "resolved" })}
            disabled={act.isPending || incident.status === "resolved"}
            className="rounded border border-line px-2 py-1 text-xs transition hover:text-accent disabled:opacity-40"
          >
            Resolve
          </button>
        </div>
      )}

      {act.error && (
        <div className="px-4">
          <ErrorNote error={act.error} fallback="Could not apply that." />
        </div>
      )}

      <div className="px-4 py-3">
        {user?.is_staff && (
          <Row label="Client">
            <TenantChip name={incident.tenant_name} colour={incident.tenant_colour} />
          </Row>
        )}
        <Row label="Assignee">
          {incident.assignee_name ?? <span className="text-dim">Unassigned</span>}
        </Row>
        <Row label="SLA">
          <SlaClock incident={incident} />
        </Row>
        <Row label="Alerts">
          <span className="data">{incident.alert_count}</span>
        </Row>
        <Row label="First seen">
          <span className="data text-xs text-dim">{relative(incident.first_seen)}</span>
        </Row>
        <Row label="Last seen">
          <span className="data text-xs text-dim">{relative(incident.last_seen)}</span>
        </Row>
        {incident.classification && (
          <Row label="Class">{incident.classification}</Row>
        )}
      </div>

      {Object.keys(rules).length > 0 && (
        <div className="border-t border-line px-4 py-3">
          <p className="text-xs text-dim">Rules</p>
          <ul className="mt-1.5 space-y-1">
            {Object.entries(rules)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 6)
              .map(([ruleId, count]) => (
                <li key={ruleId} className="flex items-baseline gap-2 text-xs">
                  <Link
                    to={`/alerts?rule_id=${ruleId}`}
                    className="data transition hover:text-accent"
                  >
                    {ruleId}
                  </Link>
                  <span className="data ml-auto text-dim">{count}</span>
                </li>
              ))}
          </ul>
        </div>
      )}

      {entities.data && entities.data.length > 0 && (
        <div className="border-t border-line px-4 py-3">
          <p className="text-xs text-dim">Entities</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {entities.data.slice(0, 12).map((entity) => (
              <Link
                key={entity.id}
                to={`/entities/${entity.type}/${encodeURIComponent(entity.value)}`}
                className="data rounded bg-ink-700 px-1.5 py-0.5 text-xs text-dim transition hover:text-accent"
                title={`${entity.type} · ${entity.alert_count} alerts`}
              >
                {entity.value}
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="mt-auto border-t border-line px-4 py-3">
        <Link
          to={href}
          className="flex items-center gap-1.5 text-sm text-accent transition hover:brightness-110"
        >
          View full details
          <ExternalLink size={13} />
        </Link>
        <p className="mt-1 text-xs text-dim">
          Timeline, every alert, and the comment thread.
        </p>
      </div>
    </aside>
  );
}
