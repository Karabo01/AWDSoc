import { api } from "./client";

export type EntityType = "ip" | "user" | "host" | "hash";

export interface AlertSummary {
  id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  tenant_colour: string | null;
  timestamp: string;
  rule_id: number;
  rule_level: number;
  rule_desc: string;
  rule_groups: string[];
  mitre_ids: string[];
  agent_id: string | null;
  agent_name: string | null;
  incident_id: string | null;
  map_version: number;
}

export interface AlertDetail extends AlertSummary {
  received_at: string;
  wazuh_id: string;
  mitre_tactics: string[];
  fingerprint: string;
  ecs: Record<string, unknown>;
  raw: Record<string, unknown>;
  related_ip: string[];
  related_user: string[];
  related_host: string[];
  related_hash: string[];
}

export interface AlertPage {
  items: AlertSummary[];
  next_cursor: string | null;
}

export interface AlertFilters {
  severity_min?: number;
  rule_id?: number;
  agent_id?: string;
  entity_type?: EntityType;
  entity_value?: string;
  map_version?: number;
  q?: string;
  from?: string;
  to?: string;
}

export function listAlerts(filters: AlertFilters, cursor?: string, limit = 50) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "" && value !== null) {
      params.set(key, String(value));
    }
  }
  if (cursor) params.set("cursor", cursor);
  params.set("limit", String(limit));
  return api<AlertPage>(`/alerts?${params.toString()}`);
}

export const getAlert = (id: string) => api<AlertDetail>(`/alerts/${id}`);
