import { api } from "./client";

/** The frozen snapshot. Typed loosely on purpose: a report issued today must
 *  still render in two years, after the builder has grown fields and dropped
 *  others, so every section is optional and the view degrades rather than
 *  throwing. `schema` carries the version. */
export interface ReportPayload {
  schema?: number;
  tenant?: { name: string; slug: string };
  period?: { start: string; end: string };
  generated_at?: string;
  alerts?: {
    total: number;
    first_at: string | null;
    last_at: string | null;
    top_rules: {
      rule_id: number;
      description: string;
      level: number;
      count: number;
    }[];
    top_techniques: { technique_id: string; count: number }[];
  };
  incidents?: {
    opened: number;
    closed: number;
    still_open: number;
    critical_opened: number;
    by_severity: Record<string, number>;
    by_classification: Record<string, number>;
    false_positives: number;
  };
  sla?: {
    configured: boolean;
    bands?: {
      severity_min: number;
      respond_minutes: number;
      resolve_minutes: number;
    }[];
    measured?: number;
    responded?: number;
    response_breached?: number;
    resolution_measured?: number;
    resolution_breached?: number;
    response_met_pct?: number | null;
    median_response_minutes?: number | null;
    awaiting_client_hours?: number;
  };
  notable_incidents?: {
    number: number;
    title: string;
    severity: number;
    status: string;
    classification: string | null;
    alert_count: number;
    first_seen: string;
    closed_at: string | null;
    response_breached: boolean;
    client_updates: number;
  }[];
  coverage?: {
    agents_total: number;
    agents_active: number;
    agents_disconnected: number;
    alert_floor: number;
  };
}

export interface ReportSummary {
  id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  number: number;
  title: string;
  status: "draft" | "issued";
  period_start: string;
  period_end: string;
  generated_at: string;
  generated_by_name: string | null;
  issued_at: string | null;
}

export interface Report extends ReportSummary {
  summary_note: string | null;
  payload: ReportPayload;
}

export interface ReportPreview {
  period_start: string;
  period_end: string;
  payload: ReportPayload;
}

export interface ReportRequest {
  period_start: string;
  period_end: string;
  title?: string;
  summary_note?: string;
}

export const listReports = () => api<ReportSummary[]>("/reports");

export const previewReport = (body: ReportRequest) =>
  api<ReportPreview>("/reports/preview", { method: "POST", body });

export const createReport = (body: ReportRequest) =>
  api<Report>("/reports", { method: "POST", body });

export const getReport = (id: string) => api<Report>(`/reports/${id}`);

export const updateReport = (
  id: string,
  body: { title?: string; summary_note?: string | null },
) => api<Report>(`/reports/${id}`, { method: "PATCH", body });

/** One way. After this the client can see it and the wording is frozen. */
export const issueReport = (id: string) =>
  api<Report>(`/reports/${id}/issue`, { method: "POST" });

export const deleteReport = (id: string) =>
  api<void>(`/reports/${id}`, { method: "DELETE" });
