import { api } from "./client";
import type { AlertPage } from "./alerts";

export type IncidentStatus =
  | "new"
  | "active"
  | "pending"
  | "resolved"
  | "false_positive";

export interface IncidentSummary {
  id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  tenant_colour: string | null;
  number: number;
  title: string;
  status: IncidentStatus;
  severity: number;
  classification: string | null;
  assignee_id: string | null;
  assignee_name: string | null;
  first_seen: string;
  last_seen: string;
  alert_count: number;
  sla_respond_by: string | null;
  sla_resolve_by: string | null;
  /** Non-null means the clock is stopped awaiting the client. */
  sla_paused_at: string | null;
  sla_paused_seconds: number;
  first_response_at: string | null;
  response_breached: boolean;
  resolution_breached: boolean;
  created_at: string;
  updated_at: string;
}

export interface IncidentDetail extends IncidentSummary {
  fingerprint: string;
  rule_summary: Record<string, number>;
  evidence: Record<string, unknown>;
  related_incident_id: string | null;
  closed_at: string | null;
}

export interface IncidentPage {
  items: IncidentSummary[];
  next_cursor: string | null;
}

export interface Comment {
  id: string;
  incident_id: string;
  user_id: string;
  author_name: string | null;
  body: string;
  visibility: "internal" | "client";
  created_at: string;
}

export interface TimelineEntry {
  at: string;
  kind: "alert" | "comment" | "audit";
  summary: string;
  detail: Record<string, unknown>;
}

export interface IncidentEntity {
  id: string;
  type: string;
  value: string;
  first_seen: string;
  last_seen: string;
  alert_count: number;
  role: string | null;
}

export type SortKey =
  | "last_seen"
  | "first_seen"
  | "created_at"
  | "severity"
  | "number"
  | "alert_count";

export interface IncidentFilters {
  status?: string[];
  severity_min?: number;
  assignee?: string;
  q?: string;
  open_only?: boolean;
  sort?: SortKey;
  order?: "asc" | "desc";
}

export function listIncidents(filters: IncidentFilters, cursor?: string, limit = 50) {
  const params = new URLSearchParams();
  filters.status?.forEach((s) => params.append("status", s));
  if (filters.severity_min) params.set("severity_min", String(filters.severity_min));
  if (filters.assignee) params.set("assignee", filters.assignee);
  if (filters.q) params.set("q", filters.q);
  if (filters.open_only) params.set("open_only", "true");
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.order) params.set("order", filters.order);
  if (cursor) params.set("cursor", cursor);
  params.set("limit", String(limit));
  return api<IncidentPage>(`/incidents?${params.toString()}`);
}

export const getIncidentByNumber = (slug: string, number: number) =>
  api<IncidentDetail>(`/incidents/by-number/${slug}/${number}`);

export const patchIncident = (id: string, body: Record<string, unknown>) =>
  api<IncidentDetail>(`/incidents/${id}`, { method: "PATCH", body });

export const incidentAlerts = (id: string) =>
  api<AlertPage>(`/incidents/${id}/alerts`);

export const incidentComments = (id: string) =>
  api<Comment[]>(`/incidents/${id}/comments`);

export const addComment = (id: string, body: string, visibility: string) =>
  api<Comment>(`/incidents/${id}/comments`, {
    method: "POST",
    body: { body, visibility },
  });

export const incidentTimeline = (id: string) =>
  api<TimelineEntry[]>(`/incidents/${id}/timeline`);

export const incidentEntities = (id: string) =>
  api<IncidentEntity[]>(`/incidents/${id}/entities`);

export interface BulkResult {
  updated: string[];
  /** Cases the token could not reach, or that needed no change. Kept separate so
   *  a partial success reads as one rather than as a silent failure. */
  skipped: string[];
  reason: string | null;
}

export const bulkUpdate = (body: {
  incident_ids: string[];
  status?: string;
  assignee_id?: string | null;
  assign_to_me?: boolean;
  classification?: string;
}) => api<BulkResult>("/incidents/bulk", { method: "POST", body });
