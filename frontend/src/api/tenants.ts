import { api } from "./client";

export interface SlaBand {
  severity_min: number;
  respond_minutes: number;
  resolve_minutes: number;
}

export interface SlaPolicy {
  bands: SlaBand[];
}

export interface WazuhConnectionRead {
  base_url: string;
  username: string;
  verify_ssl: boolean;
  agent_group: string | null;
  last_sync_at: string | null;
  last_sync_error: string | null;
}

export interface Tenant {
  id: string;
  slug: string;
  name: string;
  status: "active" | "suspended" | "offboarding";
  alert_floor: number;
  grouping_window_minutes: number;
  ingest_cidrs: string[];
  colour: string | null;
  created_at: string;
  connection: WazuhConnectionRead | null;
  sla: SlaPolicy | null;
}

/** The one and only time an ingest secret is readable. There is no endpoint
 *  that returns it again — rotation is the only recovery. */
export interface TenantSecretRevealed {
  tenant: Tenant;
  ingest_secret: string;
  ingest_url: string;
  integration_block: string;
  install_command: string;
}

export interface ConnectionCheckResult {
  ok: boolean;
  error: string | null;
  manager_version: string | null;
  node_name: string | null;
  agent_count: number | null;
  agent_group: string | null;
  agent_group_exists: boolean | null;
  agent_group_count: number | null;
  warnings: string[];
}

export interface TenantCreatePayload {
  slug: string;
  name: string;
  alert_floor: number;
  grouping_window_minutes: number;
  ingest_cidrs: string[];
  connection?: {
    base_url: string;
    username: string;
    password: string;
    verify_ssl: boolean;
    agent_group: string | null;
  };
  sla?: SlaPolicy;
}

export const listTenants = () => api<Tenant[]>("/tenants");

export const createTenant = (body: TenantCreatePayload) =>
  api<TenantSecretRevealed>("/tenants", { method: "POST", body });

export const rotateSecret = (id: string) =>
  api<TenantSecretRevealed>(`/tenants/${id}/rotate-secret`, { method: "POST" });

export const testConnection = (id: string) =>
  api<ConnectionCheckResult>(`/tenants/${id}/test-connection`, { method: "POST" });

export const updateTenant = (id: string, body: Record<string, unknown>) =>
  api<Tenant>(`/tenants/${id}`, { method: "PATCH", body });

export const putSla = (id: string, policy: SlaPolicy) =>
  api<SlaPolicy>(`/tenants/${id}/sla`, { method: "PUT", body: policy });
