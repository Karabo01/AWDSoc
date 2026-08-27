import { api } from "./client";
import type { Role } from "./types";

export interface UserRead {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_staff: boolean;
  is_active: boolean;
  tenant_id: string | null;
  tenant_name: string | null;
  last_login_at: string | null;
  created_at: string;
}

/** The password comes back exactly once. There is no endpoint that reads it
 *  again — a reset is the only recovery. */
export interface UserCreated {
  user: UserRead;
  password: string | null;
}

export interface AuditEntry {
  id: number;
  tenant_id: string | null;
  user_id: string | null;
  actor_name: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface AuditPage {
  items: AuditEntry[];
  next_before_id: number | null;
}

export const listUsers = (includeInactive = false) =>
  api<UserRead[]>(`/users?include_inactive=${includeInactive}`);

export const createUser = (body: {
  email: string;
  full_name: string;
  role: Role;
  tenant_id?: string | null;
}) => api<UserCreated>("/users", { method: "POST", body });

export const updateUser = (
  id: string,
  body: { full_name?: string; role?: Role; is_active?: boolean },
) => api<UserRead>(`/users/${id}`, { method: "PATCH", body });

/** Returns the same write-once shape as creation — the API has exactly one
 *  response model that carries a password, deliberately. */
export const resetPassword = (id: string) =>
  api<UserCreated>(`/users/${id}/reset-password`, { method: "POST" });

export function listAudit(
  filters: { action?: string; target_id?: string } = {},
  beforeId?: number,
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, String(value));
  }
  if (beforeId) params.set("before_id", String(beforeId));
  return api<AuditPage>(`/audit?${params.toString()}`);
}
