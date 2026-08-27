import type { IncidentStatus } from "@/api/incidents";

const LABELS: Record<IncidentStatus, string> = {
  new: "New",
  active: "Active",
  pending: "Awaiting client",
  resolved: "Resolved",
  false_positive: "False positive",
};

const STYLES: Record<IncidentStatus, string> = {
  new: "bg-[rgba(224,163,46,.12)] text-[color:var(--sev-med)]",
  active: "bg-ink-700 text-text",
  pending: "bg-ink-700 text-dim",
  resolved: "bg-ink-700 text-dim",
  false_positive: "bg-ink-700 text-dim",
};

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs ${STYLES[status]}`}>
      {LABELS[status]}
    </span>
  );
}
