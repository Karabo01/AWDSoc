import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type EntityType,
  PIVOTABLE,
  entityAlerts,
  entityIncidents,
  getEntity,
  setEntityNotes,
} from "@/api/entities";
import { SeverityChip } from "@/components/SeverityChip";
import { Empty, ErrorNote, Loading, relative } from "@/components/States";
import { StatusBadge } from "@/components/StatusBadge";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-line bg-ink-800 px-3 py-2">
      <p className="text-xs text-dim">{label}</p>
      <p className="data mt-1 text-lg">{value}</p>
    </div>
  );
}

/** One observed value, and everything the console knows about it.
 *
 *  The two lists below come from different indexes and answer different
 *  questions: alerts from the GIN array pivot, incidents from the link table. */
export function EntityDetail() {
  // The route is `/entities/:type/*` rather than `/:type/:value` because an
  // entity value can contain a slash - a file path, or a DOMAIN\user account.
  const params = useParams();
  const entityType = (params.type ?? "ip") as EntityType;
  const value = decodeURIComponent(params["*"] ?? "");
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const entity = useQuery({
    queryKey: ["entity", entityType, value],
    queryFn: () => getEntity(entityType, value),
  });

  const alerts = useQuery({
    queryKey: ["entity-alerts", entityType, value],
    queryFn: () => entityAlerts(entityType, value),
    enabled: PIVOTABLE.includes(entityType),
  });

  const incidents = useQuery({
    queryKey: ["entity-incidents", entityType, value],
    queryFn: () => entityIncidents(entityType, value),
  });

  const [notes, setNotes] = useState("");
  const [dirty, setDirty] = useState(false);

  // Only adopt the server's copy while the box is untouched, so a save landing
  // mid-sentence cannot overwrite what the analyst is still typing.
  useEffect(() => {
    if (!dirty && entity.data) setNotes(entity.data.notes ?? "");
  }, [entity.data, dirty]);

  const saveNotes = useMutation({
    mutationFn: () => setEntityNotes(entityType, value, notes.trim() || null),
    onSuccess: (updated) => {
      setDirty(false);
      queryClient.setQueryData(["entity", entityType, value], updated);
    },
  });

  const canAnnotate = user?.role !== "client_viewer";

  if (entity.isLoading) return <Loading what="entity" />;
  if (entity.error)
    return (
      <ErrorNote
        error={entity.error}
        fallback="Could not load that entity."
        onRetry={() => void entity.refetch()}
      />
    );
  if (!entity.data) return null;

  const data = entity.data;

  return (
    <div className="mx-auto max-w-5xl">
      <Link to="/entities" className="text-sm text-dim transition hover:text-text">
        ← Entities
      </Link>

      <div className="mt-2 flex flex-wrap items-baseline gap-3">
        <span className="rounded bg-ink-700 px-2 py-0.5 text-xs text-dim">
          {data.type}
        </span>
        <h1 className="data break-all text-lg font-semibold">{data.value}</h1>
        {user?.is_staff && (
          <TenantChip name={data.tenant_name} colour={data.tenant_colour} />
        )}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Alerts" value={data.alert_count.toLocaleString()} />
        <Stat label="Incidents" value={data.incident_count} />
        <Stat label="Open incidents" value={data.open_incident_count} />
        <Stat label="First seen" value={relative(data.first_seen)} />
      </div>

      <section className="mt-8">
        <h2 className="text-sm font-medium">Notes</h2>
        <p className="mt-1 text-sm text-dim">
          Scoped to this client. Another client seeing the same address has their own
          separate notes.
        </p>
        <textarea
          value={notes}
          onChange={(e) => {
            setNotes(e.target.value);
            setDirty(true);
          }}
          disabled={!canAnnotate}
          rows={4}
          placeholder={
            canAnnotate
              ? "Known scanner, customer VPN egress, decommissioned host…"
              : "Read-only access."
          }
          className="mt-2 w-full rounded border border-line bg-ink-900 px-3 py-2 text-sm outline-none transition focus:border-accent disabled:opacity-60"
        />
        {canAnnotate && (
          <div className="mt-2 flex items-center gap-3">
            <button
              onClick={() => saveNotes.mutate()}
              disabled={!dirty || saveNotes.isPending}
              className="rounded border border-line px-3 py-1.5 text-sm transition hover:text-accent disabled:opacity-50"
            >
              {saveNotes.isPending ? "Saving…" : "Save notes"}
            </button>
            {saveNotes.error && (
              <span className="text-xs text-[color:var(--sev-crit)]">
                Could not save.
              </span>
            )}
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium">Incidents</h2>
        {incidents.isLoading && <Loading what="incidents" />}
        {incidents.data?.items.length === 0 && (
          <Empty
            title="This entity has not been part of an incident."
            hint="It has been seen on alerts, but none of them grouped into a case."
          />
        )}
        {incidents.data && incidents.data.items.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[36rem] border-collapse text-sm">
              <tbody>
                {incidents.data.items.map((incident) => (
                  <tr key={incident.id} className="border-b border-line last:border-b-0">
                    <td className="px-3 py-1.5">
                      <SeverityChip level={incident.severity} />
                    </td>
                    <td className="px-3 py-1.5">
                      <Link
                        to={`/incidents/${incident.tenant_slug ?? "-"}/${incident.number}`}
                        className="transition hover:text-accent"
                      >
                        {incident.title}
                      </Link>
                      <span className="data ml-2 text-xs text-dim">
                        #{incident.number}
                      </span>
                    </td>
                    <td className="px-3 py-1.5">
                      <StatusBadge status={incident.status} />
                    </td>
                    <td className="data px-3 py-1.5 text-xs text-dim">
                      {relative(incident.last_seen)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium">Recent alerts</h2>
        {!PIVOTABLE.includes(entityType) ? (
          <p className="mt-2 text-sm text-dim">
            Alerts cannot be pivoted by {entityType} — only address, user, host and hash
            are indexed on the alerts table.
          </p>
        ) : (
          <>
            {alerts.isLoading && <Loading what="alerts" />}
            {alerts.data?.items.length === 0 && (
              <Empty title="No alerts reference this entity in the retained window." />
            )}
            {alerts.data && alerts.data.items.length > 0 && (
              <div className="mt-3 overflow-x-auto rounded-lg border border-line">
                <table className="w-full min-w-[40rem] border-collapse text-sm">
                  <tbody>
                    {alerts.data.items.map((alert) => (
                      <tr key={alert.id} className="border-b border-line last:border-b-0">
                        <td className="px-3 py-1.5">
                          <SeverityChip level={alert.rule_level} />
                        </td>
                        <td className="px-3 py-1.5">
                          <Link
                            to={`/alerts/${alert.id}`}
                            className="transition hover:text-accent"
                          >
                            {alert.rule_desc}
                          </Link>
                        </td>
                        <td className="data px-3 py-1.5 text-xs text-dim">
                          {alert.agent_name ?? "—"}
                        </td>
                        <td className="data px-3 py-1.5 text-xs text-dim">
                          {relative(alert.timestamp)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {alerts.data?.next_cursor && (
              <Link
                to={`/alerts?entity_type=${entityType}&entity_value=${encodeURIComponent(value)}`}
                className="mt-3 inline-block text-sm text-dim underline transition hover:text-text"
              >
                See all alerts for this entity
              </Link>
            )}
          </>
        )}
      </section>
    </div>
  );
}
