import type { IncidentSummary } from "@/api/incidents";

function humanise(ms: number): string {
  const minutes = Math.round(Math.abs(ms) / 60000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d`;
}

/** A stopped countdown that looks like a running one is how an analyst misses a
 *  case that came back, so a paused clock reads as "Paused", never as a frozen
 *  timer. */
export function SlaClock({ incident }: { incident: IncidentSummary }) {
  const closed = incident.status === "resolved" || incident.status === "false_positive";
  const deadline =
    incident.first_response_at || closed
      ? incident.sla_resolve_by
      : incident.sla_respond_by;

  if (!deadline) return <span className="text-xs text-dim">—</span>;

  if (incident.sla_paused_at) {
    return (
      <span className="rounded bg-ink-700 px-1.5 py-0.5 text-xs text-dim">
        Paused
      </span>
    );
  }

  const breached = incident.first_response_at
    ? incident.resolution_breached
    : incident.response_breached;

  if (breached) {
    return (
      <span className="data rounded bg-[rgba(224,67,95,.14)] px-1.5 py-0.5 text-xs text-[color:var(--sev-crit)]">
        Breached
      </span>
    );
  }

  if (closed) return <span className="text-xs text-dim">Met</span>;

  const remaining = new Date(deadline).getTime() - Date.now();
  const urgent = remaining < 15 * 60 * 1000;

  return (
    <span
      className={`data text-xs ${urgent ? "text-[color:var(--sev-high)]" : "text-dim"}`}
      title={`Due ${new Date(deadline).toLocaleString()}`}
    >
      {humanise(remaining)} left
    </span>
  );
}
