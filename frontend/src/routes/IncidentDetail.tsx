import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import {
  type IncidentStatus,
  addComment,
  getIncidentByNumber,
  incidentAlerts,
  incidentComments,
  incidentEntities,
  incidentTimeline,
  patchIncident,
} from "@/api/incidents";
import { SeverityChip } from "@/components/SeverityChip";
import { SlaClock } from "@/components/SlaClock";
import { StatusBadge } from "@/components/StatusBadge";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

// Named by what the analyst controls, not by the field being set.
const ACTIONS: { status: IncidentStatus; label: string }[] = [
  { status: "active", label: "Start work" },
  { status: "pending", label: "Wait on client" },
  { status: "resolved", label: "Resolve" },
  { status: "false_positive", label: "Mark false positive" },
];

function held(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function IncidentDetail() {
  const { tenant, number } = useParams<{ tenant: string; number: string }>();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [shareWithClient, setShareWithClient] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const { data: incident, isLoading, error } = useQuery({
    queryKey: ["incident", tenant, number],
    queryFn: () => getIncidentByNumber(tenant!, Number(number)),
    enabled: Boolean(tenant && number),
  });

  const id = incident?.id;

  const { data: comments } = useQuery({
    queryKey: ["incident-comments", id],
    queryFn: () => incidentComments(id!),
    enabled: Boolean(id),
  });
  const { data: timeline } = useQuery({
    queryKey: ["incident-timeline", id],
    queryFn: () => incidentTimeline(id!),
    enabled: Boolean(id),
  });
  const { data: entities } = useQuery({
    queryKey: ["incident-entities", id],
    queryFn: () => incidentEntities(id!),
    enabled: Boolean(id),
  });
  const { data: alerts } = useQuery({
    queryKey: ["incident-alerts", id],
    queryFn: () => incidentAlerts(id!),
    enabled: Boolean(id),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["incident", tenant, number] });
    void queryClient.invalidateQueries({ queryKey: ["incident-timeline", id] });
    void queryClient.invalidateQueries({ queryKey: ["incident-comments", id] });
  }

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => patchIncident(id!, body),
    onSuccess: (_data, body) => {
      refresh();
      // The button that says "Resolve" produces a toast that says "Resolved".
      const spoken: Record<string, string> = {
        active: "Started",
        pending: "Waiting on client — SLA clock stopped",
        resolved: "Resolved",
        false_positive: "Marked false positive",
      };
      const status = body.status as string | undefined;
      setToast(status ? spoken[status] : "Assigned to you");
      setTimeout(() => setToast(null), 2600);
    },
  });

  const postComment = useMutation({
    mutationFn: () =>
      addComment(id!, comment, shareWithClient ? "client" : "internal"),
    onSuccess: () => {
      setComment("");
      setShareWithClient(false);
      refresh();
    },
  });

  if (isLoading) return <p className="p-6 text-sm text-dim">Loading incident…</p>;
  if (error) {
    return (
      <p className="p-6 text-sm text-[color:var(--sev-crit)]">
        {error instanceof ApiError ? error.message : "Could not load this incident."}
      </p>
    );
  }
  if (!incident) return null;

  const readOnly = user?.role === "client_viewer";

  return (
    <div className="mx-auto max-w-6xl">
      <Link to="/incidents" className="text-sm text-dim transition hover:text-text">
        ← Incidents
      </Link>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <SeverityChip level={incident.severity} />
        <h1 className="text-lg font-semibold">{incident.title}</h1>
        <span className="data text-sm text-dim">#{incident.number}</span>
        <TenantChip name={incident.tenant_name} colour={incident.tenant_colour} />
        <StatusBadge status={incident.status} />
        <SlaClock incident={incident} />
      </div>

      <div className="data mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-dim">
        <span>{incident.alert_count} alerts</span>
        <span>first {new Date(incident.first_seen).toLocaleString()}</span>
        <span>last {new Date(incident.last_seen).toLocaleString()}</span>
        {incident.assignee_name && <span>assigned {incident.assignee_name}</span>}
        {incident.sla_paused_seconds > 0 && (
          <span>held {held(incident.sla_paused_seconds)} awaiting client</span>
        )}
      </div>

      {incident.related_incident_id && (
        <p className="mt-3 rounded border border-line bg-ink-800 p-3 text-sm text-dim">
          This recurred — a case with the same fingerprint was resolved in the last
          week. Reopening is never automatic, so this is a new incident linked to the
          old one.
        </p>
      )}

      {toast && (
        <p
          role="status"
          className="mt-4 rounded border border-accent/40 bg-ink-800 px-3 py-2 text-sm"
        >
          {toast}
        </p>
      )}

      {!readOnly && (
        <div className="mt-5 flex flex-wrap gap-2">
          {!incident.assignee_id && (
            <button
              onClick={() => update.mutate({ assign_to_me: true })}
              disabled={update.isPending}
              className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
            >
              Assign to me
            </button>
          )}
          {ACTIONS.filter((a) => a.status !== incident.status).map((action) => (
            <button
              key={action.status}
              onClick={() => update.mutate({ status: action.status })}
              disabled={update.isPending}
              className="rounded border border-line px-3 py-1.5 text-sm text-dim transition hover:text-text disabled:opacity-60"
            >
              {action.label}
            </button>
          ))}
        </div>
      )}

      {incident.status === "pending" && (
        <p className="mt-3 text-xs text-dim">
          The SLA clock is stopped while this waits on the client. It resumes, pushed
          forward by the time held, as soon as the status changes.
        </p>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="text-sm font-medium">Timeline</h2>
          <div className="mt-2 rounded-lg border border-line bg-ink-800">
            {timeline?.length === 0 && (
              <p className="p-4 text-sm text-dim">Nothing recorded yet.</p>
            )}
            {timeline?.map((entry, index) => (
              <div
                key={`${entry.at}-${index}`}
                className="border-b border-line p-3 last:border-b-0"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="data text-xs text-dim">
                    {new Date(entry.at).toLocaleString()}
                  </span>
                  <span className="text-xs text-dim">{entry.kind}</span>
                </div>
                <p className="mt-1 text-sm">{entry.summary}</p>
                {entry.kind === "comment" && (
                  <p className="mt-1 whitespace-pre-wrap text-sm text-dim">
                    {String(entry.detail.body ?? "")}
                  </p>
                )}
                {entry.kind === "alert" && (
                  <Link
                    to={`/alerts/${String(entry.detail.alert_id)}`}
                    className="data mt-1 inline-block text-xs text-dim underline transition hover:text-accent"
                  >
                    rule {String(entry.detail.rule_id)} · level{" "}
                    {String(entry.detail.rule_level)}
                  </Link>
                )}
              </div>
            ))}
          </div>

          {!readOnly && (
            <div className="mt-6 rounded-lg border border-line bg-ink-800 p-4">
              <h2 className="text-sm font-medium">Add a note</h2>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={3}
                className="mt-2 w-full rounded border border-line bg-ink-900 px-3 py-2 text-sm outline-none transition focus:border-accent"
              />
              {user?.is_staff && (
                <label className="mt-2 flex items-center gap-2 text-sm text-dim">
                  <input
                    type="checkbox"
                    checked={shareWithClient}
                    onChange={(e) => setShareWithClient(e.target.checked)}
                  />
                  Share with client
                </label>
              )}
              <button
                onClick={() => postComment.mutate()}
                disabled={!comment.trim() || postComment.isPending}
                className="mt-3 rounded bg-accent px-3 py-1.5 text-sm font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
              >
                {postComment.isPending ? "Saving…" : "Add note"}
              </button>
              {comments && comments.length > 0 && (
                <p className="mt-2 text-xs text-dim">
                  {comments.filter((c) => c.visibility === "client").length} shared with
                  the client
                </p>
              )}
            </div>
          )}
        </div>

        <div>
          <h2 className="text-sm font-medium">Entities</h2>
          <div className="mt-2 rounded-lg border border-line bg-ink-800 p-3">
            {entities?.length === 0 && (
              <p className="text-sm text-dim">None extracted.</p>
            )}
            {entities?.map((entity) => (
              <Link
                key={entity.id}
                to={`/alerts?entity_type=${entity.type}&entity_value=${encodeURIComponent(entity.value)}`}
                className="data mb-1.5 mr-1.5 inline-block rounded border border-line bg-ink-900 px-1.5 py-0.5 text-xs transition hover:border-accent hover:text-accent"
                title={`${entity.type} · seen in ${entity.alert_count} alerts`}
              >
                {entity.value}
              </Link>
            ))}
          </div>

          <h2 className="mt-6 text-sm font-medium">Rules</h2>
          <div className="mt-2 rounded-lg border border-line bg-ink-800 p-3">
            {Object.entries(incident.rule_summary)
              .filter(([key]) => !key.startsWith("_"))
              .map(([ruleId, count]) => (
                <p key={ruleId} className="data text-xs text-dim">
                  {ruleId} × {count}
                </p>
              ))}
          </div>

          <h2 className="mt-6 text-sm font-medium">Member alerts</h2>
          <div className="mt-2 rounded-lg border border-line bg-ink-800 p-3">
            {alerts?.items.slice(0, 10).map((alert) => (
              <Link
                key={alert.id}
                to={`/alerts/${alert.id}`}
                className="mb-1 block text-xs text-dim transition hover:text-accent"
              >
                <span className="data">
                  {new Date(alert.timestamp).toLocaleTimeString()}
                </span>{" "}
                {alert.rule_desc}
              </Link>
            ))}
            {alerts && alerts.items.length === 0 && (
              <p className="text-sm text-dim">
                No member alerts remain — they age out at 90 days. The evidence snapshot
                on this case is what survives.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
