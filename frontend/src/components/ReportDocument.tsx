import type { ReportPayload } from "@/api/reports";

/** The report itself, as the client reads it.
 *
 *  Every section guards its own data. A report issued a year ago was built by an
 *  older builder, and a missing section must render as absent rather than as a
 *  crash — see the note on `ReportPayload`.
 *
 *  Printing is the delivery mechanism for now, so this is laid out for paper:
 *  print styles live in `tokens.css` under `@media print` and force a light
 *  ground, because a dark-theme console printed as-is is a page of black ink. */

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="report-section mt-8">
      <h2 className="border-b border-line pb-1 text-sm font-semibold uppercase tracking-wide">
        {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded border border-line px-3 py-2">
      <p className="text-xs text-dim">{label}</p>
      <p className="data mt-1 text-xl">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-dim">{hint}</p>}
    </div>
  );
}

function date(value: string | undefined | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const SEVERITY_LABELS: Record<string, string> = {
  critical: "Critical (13–15)",
  high: "High (10–12)",
  medium: "Medium (7–9)",
  low: "Low (0–6)",
};

export function ReportDocument({
  payload,
  title,
  note,
}: {
  payload: ReportPayload;
  title: string;
  note?: string | null;
}) {
  const { alerts, incidents, sla, coverage } = payload;
  const notable = payload.notable_incidents ?? [];

  return (
    <article className="report-document">
      <header>
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-1 text-sm text-dim">
          {payload.tenant?.name} · {date(payload.period?.start)} to{" "}
          {date(payload.period?.end)}
        </p>
        <p className="mt-0.5 text-xs text-dim">
          Prepared by AWDTECH · generated {date(payload.generated_at)}
        </p>
      </header>

      {note && (
        <Section title="Summary">
          <p className="max-w-prose whitespace-pre-wrap text-sm leading-relaxed">{note}</p>
        </Section>
      )}

      {incidents && (
        <Section title="Incidents">
          <div className="grid gap-3 sm:grid-cols-4">
            <Figure label="Opened" value={incidents.opened} />
            <Figure label="Closed" value={incidents.closed} />
            <Figure
              label="Still open"
              value={incidents.still_open}
              hint="At time of generation"
            />
            <Figure
              label="Critical"
              value={incidents.critical_opened}
              hint="Level 13 and above"
            />
          </div>

          <div className="mt-4 grid gap-6 sm:grid-cols-2">
            <div>
              <p className="text-xs text-dim">Opened by severity</p>
              <table className="mt-1.5 w-full text-sm">
                <tbody>
                  {Object.entries(incidents.by_severity ?? {}).map(([band, count]) => (
                    <tr key={band} className="border-b border-line last:border-b-0">
                      <td className="py-1">{SEVERITY_LABELS[band] ?? band}</td>
                      <td className="data py-1 text-right">{count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div>
              <p className="text-xs text-dim">Closed by classification</p>
              {Object.keys(incidents.by_classification ?? {}).length === 0 ? (
                <p className="mt-1.5 text-sm text-dim">
                  No cases were closed in this period.
                </p>
              ) : (
                <table className="mt-1.5 w-full text-sm">
                  <tbody>
                    {Object.entries(incidents.by_classification).map(([name, count]) => (
                      <tr key={name} className="border-b border-line last:border-b-0">
                        <td className="py-1">{name}</td>
                        <td className="data py-1 text-right">{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </Section>
      )}

      {sla && (
        <Section title="Service levels">
          {!sla.configured ? (
            <p className="max-w-prose text-sm text-dim">
              No service level agreement is configured for this account, so response
              times are not measured against a target. This section will report
              performance once one is in place.
            </p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-4">
                <Figure
                  label="Response met"
                  value={
                    sla.response_met_pct === null || sla.response_met_pct === undefined
                      ? "—"
                      : `${sla.response_met_pct}%`
                  }
                  hint={`${sla.measured ?? 0} case${sla.measured === 1 ? "" : "s"} measured`}
                />
                <Figure
                  label="Response breaches"
                  value={sla.response_breached ?? 0}
                />
                <Figure
                  label="Resolution breaches"
                  value={sla.resolution_breached ?? 0}
                />
                <Figure
                  label="Median response"
                  value={
                    sla.median_response_minutes === null ||
                    sla.median_response_minutes === undefined
                      ? "—"
                      : `${sla.median_response_minutes}m`
                  }
                />
              </div>

              {(sla.awaiting_client_hours ?? 0) > 0 && (
                <p className="mt-3 max-w-prose text-sm text-dim">
                  The clock was stopped for{" "}
                  <span className="data">{sla.awaiting_client_hours}</span> hours in total
                  while cases were awaiting information from your team. Paused time does
                  not count toward a breach.
                </p>
              )}

              {sla.bands && sla.bands.length > 0 && (
                <table className="mt-4 w-full text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-dim">
                      <th className="py-1 text-xs font-medium">Severity</th>
                      <th className="py-1 text-xs font-medium">Respond within</th>
                      <th className="py-1 text-xs font-medium">Resolve within</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sla.bands.map((band) => (
                      <tr
                        key={band.severity_min}
                        className="border-b border-line last:border-b-0"
                      >
                        <td className="data py-1">Level {band.severity_min}+</td>
                        <td className="data py-1">{band.respond_minutes} min</td>
                        <td className="data py-1">{band.resolve_minutes} min</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </Section>
      )}

      {notable.length > 0 && (
        <Section title="Notable incidents">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-dim">
                <th className="py-1 text-xs font-medium">#</th>
                <th className="py-1 text-xs font-medium">Incident</th>
                <th className="py-1 text-xs font-medium">Level</th>
                <th className="py-1 text-xs font-medium">Status</th>
                <th className="py-1 text-xs font-medium">Opened</th>
              </tr>
            </thead>
            <tbody>
              {notable.map((incident) => (
                <tr key={incident.number} className="border-b border-line last:border-b-0">
                  <td className="data py-1.5 pr-2">{incident.number}</td>
                  <td className="py-1.5 pr-2">
                    {incident.title}
                    {incident.classification && (
                      <span className="ml-2 text-xs text-dim">
                        {incident.classification}
                      </span>
                    )}
                  </td>
                  <td className="data py-1.5 pr-2">{incident.severity}</td>
                  <td className="py-1.5 pr-2 text-xs">
                    {incident.status === "false_positive"
                      ? "False positive"
                      : incident.status === "pending"
                        ? "Awaiting you"
                        : incident.status.charAt(0).toUpperCase() +
                          incident.status.slice(1)}
                  </td>
                  <td className="data py-1.5 text-xs text-dim">
                    {date(incident.first_seen)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {alerts && (
        <Section title="Detection activity">
          <div className="grid gap-3 sm:grid-cols-3">
            <Figure
              label="Alerts processed"
              value={alerts.total.toLocaleString()}
              hint={`At level ${coverage?.alert_floor ?? 7} and above`}
            />
            <Figure
              label="Agents reporting"
              value={
                coverage ? `${coverage.agents_active}/${coverage.agents_total}` : "—"
              }
              hint={
                coverage && coverage.agents_disconnected > 0
                  ? `${coverage.agents_disconnected} disconnected`
                  : undefined
              }
            />
            <Figure
              label="Distinct techniques"
              value={alerts.top_techniques?.length ?? 0}
              hint="MITRE ATT&CK, in the top rules"
            />
          </div>

          {alerts.top_rules && alerts.top_rules.length > 0 && (
            <>
              <p className="mt-4 text-xs text-dim">Most frequent detections</p>
              <table className="mt-1.5 w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-dim">
                    <th className="py-1 text-xs font-medium">Rule</th>
                    <th className="py-1 text-xs font-medium">Level</th>
                    <th className="py-1 text-right text-xs font-medium">Alerts</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.top_rules.map((rule) => (
                    <tr
                      key={rule.rule_id}
                      className="border-b border-line last:border-b-0"
                    >
                      <td className="py-1.5 pr-2">
                        {rule.description}
                        <span className="data ml-2 text-xs text-dim">
                          {rule.rule_id}
                        </span>
                      </td>
                      <td className="data py-1.5">{rule.level}</td>
                      <td className="data py-1.5 text-right">
                        {rule.count.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {alerts.top_techniques && alerts.top_techniques.length > 0 && (
            <>
              <p className="mt-4 text-xs text-dim">Techniques observed</p>
              <p className="data mt-1.5 text-sm">
                {alerts.top_techniques
                  .map((t) => `${t.technique_id} (${t.count})`)
                  .join(" · ")}
              </p>
            </>
          )}
        </Section>
      )}

      <footer className="mt-10 border-t border-line pt-3 text-xs text-dim">
        <p>
          Prepared by AWDTECH from monitored telemetry for the period shown. Figures are
          a snapshot taken at generation and do not change afterwards. Alert data is
          retained for 90 days.
        </p>
      </footer>
    </article>
  );
}
