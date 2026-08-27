import type { AlertPage } from "./alerts";
import { api } from "./client";

export interface AgentSummary {
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  tenant_colour: string | null;
  agent_id: string;
  name: string;
  ip: string | null;
  os_platform: string | null;
  os_name: string | null;
  version: string | null;
  status: string | null;
  groups: string[];
  last_keepalive: string | null;
  /** Everything here is a cache of the client's manager. Show this, always. */
  synced_at: string;
}

export interface AgentDetail extends AgentSummary {
  alerts_24h: number;
  open_incidents: number;
  last_alert_at: string | null;
  /** Non-null means this agent id is cached under more than one client on the
   *  same manager — a group misconfiguration, and a cross-tenant leak. */
  misgrouped_with: string[] | null;
}

export interface AgentPage {
  items: AgentSummary[];
  next_cursor: string | null;
}

export interface SyncReport {
  tenant_id: string;
  tenant_slug: string | null;
  ok: boolean;
  synced: number;
  removed: number;
  error: string | null;
  warnings: string[];
}

export interface RuleRead {
  id: number;
  level: number | null;
  description: string | null;
  groups: string[];
  mitre_ids: string[];
  pci_dss: string[];
  gdpr: string[];
  hipaa: string[];
  nist_800_53: string[];
  filename: string | null;
  relative_dirname: string | null;
  cached_at: string | null;
  /** True when the manager could not be reached and this is a cached or
   *  reconstructed copy. Say so rather than implying it is current. */
  stale: boolean;
}

export interface TechniqueCoverage {
  technique_id: string;
  alert_count: number;
  incident_count: number;
  last_seen: string | null;
  max_severity: number;
}

export interface TacticCoverage {
  tactic: string;
  alert_count: number;
  technique_count: number;
}

export interface CoverageReport {
  since: string;
  techniques: TechniqueCoverage[];
  tactics: TacticCoverage[];
  unmapped_alerts: number;
  total_alerts: number;
}

export interface AgentFilters {
  status?: string;
  group?: string;
  q?: string;
}

export function listAgents(filters: AgentFilters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, String(value));
  }
  const query = params.toString();
  return api<AgentPage>(`/agents${query ? `?${query}` : ""}`);
}

export const getAgent = (agentId: string) =>
  api<AgentDetail>(`/agents/${encodeURIComponent(agentId)}`);

export const agentAlerts = (agentId: string, cursor?: string) =>
  api<AlertPage>(
    `/agents/${encodeURIComponent(agentId)}/alerts${
      cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""
    }`,
  );

/** Reaches out to every client's manager, so it is as slow as the slowest one. */
export const syncAgents = (tenantId?: string) =>
  api<SyncReport[]>(`/agents/sync${tenantId ? `?tenant_id=${tenantId}` : ""}`, {
    method: "POST",
  });

export const getRule = (ruleId: number) => api<RuleRead>(`/rules/${ruleId}`);

export const getCoverage = (days = 30) =>
  api<CoverageReport>(`/coverage/mitre?days=${days}`);
