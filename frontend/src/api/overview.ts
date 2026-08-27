import { api } from "./client";

export interface TenantOverview {
  tenant_id: string;
  name: string;
  slug: string;
  colour: string | null;
  status: string;

  open_incidents: number;
  new_incidents: number;
  unassigned_incidents: number;
  critical_open: number;
  response_breached: number;
  resolution_breached: number;
  at_risk: number;
  /** Clock stopped awaiting the client. These cannot breach. */
  awaiting_client: number;

  alerts_24h: number;
  last_alert_at: string | null;
  silent: boolean;

  agents_total: number;
  agents_active: number;
  agents_disconnected: number;
  last_sync_at: string | null;
  last_sync_error: string | null;
  has_connection: boolean;
  has_sla: boolean;
}

/** The one cross-tenant leak ingest cannot catch: the same agent id cached
 *  under two clients on the same manager means their groups overlap. */
export interface MisgroupedAgent {
  base_url: string;
  agent_id: string;
  agent_name: string | null;
  tenant_slugs: string[];
}

export interface Overview {
  scope: "tenant" | "fleet";
  generated_at: string;
  tenants: TenantOverview[];
  open_incidents: number;
  critical_open: number;
  response_breached: number;
  at_risk: number;
  alerts_24h: number;
  misgrouped_agents: MisgroupedAgent[];
  silent_tenants: string[];
}

export const getOverview = () => api<Overview>("/overview");

export interface TimeBucket {
  at: string;
  incidents: number;
  alerts: number;
  critical: number;
}

export interface SeveritySlice {
  label: string;
  severity_min: number;
  count: number;
}

export interface StatusSlice {
  status: string;
  count: number;
}

export interface OverviewTrend {
  since: string;
  /** 1 for the hourly view, 24 for the daily one. The chart labels its axis
   *  from this rather than guessing from the point spacing. */
  bucket_hours: number;
  buckets: TimeBucket[];
  by_severity: SeveritySlice[];
  by_status: StatusSlice[];
}

export const getTrend = (days = 7) =>
  api<OverviewTrend>(`/overview/trend?days=${days}`);
