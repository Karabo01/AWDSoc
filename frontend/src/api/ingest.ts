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
  /** Recent window only. A failure nobody looks at is a dropped alert. */
  failed_normalisation: number;
  awaiting_normalisation: number;
}

export interface IngestStatus {
  backlog: number;
  tenants: TenantIngest[];
}

export const getIngestStatus = () => api<IngestStatus>("/ingest/status");
