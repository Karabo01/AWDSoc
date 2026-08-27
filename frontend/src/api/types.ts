export type Role = "platform_admin" | "soc_analyst" | "client_admin" | "client_viewer";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_at: string;
}

export interface TenantSummary {
  id: string;
  slug: string;
  name: string;
  status: "active" | "suspended" | "offboarding";
  colour: string | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_staff: boolean;
  tenant_id: string | null;
  /** Staff only. null is the all-clients fleet view. */
  active_tenant: string | null;
  /** Staff only; clients never see a switcher. */
  tenants: TenantSummary[];
}

export interface Health {
  status: "ok" | "degraded";
  postgres: { ok: boolean; error: string | null };
  redis: { ok: boolean; error: string | null };
  worker: { alive: boolean };
  environment: string;
}
