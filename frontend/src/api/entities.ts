import type { AlertPage } from "./alerts";
import { api } from "./client";
import type { IncidentPage } from "./incidents";

export type EntityType = "ip" | "user" | "host" | "hash" | "process" | "file";

/** Only these four have an indexed array on `alerts`, so only these four can be
 *  pivoted. The backend returns 400 for the others rather than scanning. */
export const PIVOTABLE: EntityType[] = ["ip", "user", "host", "hash"];

export interface EntitySummary {
  id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  tenant_colour: string | null;
  type: EntityType;
  value: string;
  first_seen: string;
  last_seen: string;
  alert_count: number;
  has_notes: boolean;
}

export interface EntityDetail extends EntitySummary {
  notes: string | null;
  open_incident_count: number;
  incident_count: number;
}

export interface EntityPage {
  items: EntitySummary[];
  next_cursor: string | null;
}

export interface EntityFilters {
  type?: EntityType;
  q?: string;
  min_alerts?: number;
  last_seen_after?: string;
}

/** An entity value can contain characters that are meaningful in a path — a
 *  Windows account is `DOMAIN\user`, a file entity has slashes. Encoding it
 *  matches the `{value:path}` parameter the backend declares. */
const path = (type: EntityType, value: string) =>
  `/entities/${type}/${encodeURIComponent(value)}`;

export function listEntities(filters: EntityFilters, cursor?: string, limit = 50) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "" && value !== null) {
      params.set(key, String(value));
    }
  }
  if (cursor) params.set("cursor", cursor);
  params.set("limit", String(limit));
  return api<EntityPage>(`/entities?${params.toString()}`);
}

export const getEntity = (type: EntityType, value: string) =>
  api<EntityDetail>(path(type, value));

export const entityAlerts = (type: EntityType, value: string, cursor?: string) =>
  api<AlertPage>(
    `${path(type, value)}/alerts${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );

export const entityIncidents = (type: EntityType, value: string) =>
  api<IncidentPage>(`${path(type, value)}/incidents`);

export const setEntityNotes = (type: EntityType, value: string, notes: string | null) =>
  api<EntityDetail>(path(type, value), { method: "PATCH", body: { notes } });
