import { api } from "./client";

export interface TenantIngest {
  tenant_id: string;
  slug: string;
  name: string;
  alerts_today: number;
  bytes_today: number;
  last_alert_at: string | null;
  /** Onboarded but never delivered — almost always a misconfigured integration. */
  silent: boolean;
}

export interface IngestStatus {
  backlog: number;
  tenants: TenantIngest[];
}

export const getIngestStatus = () => api<IngestStatus>("/ingest/status");
