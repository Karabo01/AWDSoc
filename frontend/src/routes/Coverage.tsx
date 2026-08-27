import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { getCoverage } from "@/api/agents";
import { SeverityChip } from "@/components/SeverityChip";
import { Empty, ErrorNote, Loading, relative } from "@/components/States";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

/** MITRE ATT&CK coverage over detected alerts.
 *
 *  This is a report of what has fired, not of what a ruleset could catch. That
 *  distinction is stated on the page rather than left for the reader to work
 *  out, because "coverage" in a vendor console usually means the other thing and
 *  reading this as ruleset coverage would be actively misleading. */
export function Coverage() {
  const [params, setParams] = useSearchParams();
  const days = Number(params.get("days") ?? 30);

  const query = useQuery({
    queryKey: ["coverage", days],
    queryFn: () => getCoverage(days),
  });

  const data = query.data;
  const maxAlerts = data?.tactics.reduce((n, t) => Math.max(n, t.alert_count), 0) ?? 0;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">MITRE coverage</h1>
          <p className="mt-1 max-w-prose text-xs text-dim">
            What has actually been detected, not what the ruleset could detect. A
            technique missing here means nothing fired for it — which may mean nothing
            happened, or that nothing is looking.
          </p>
        </div>
        <select
          value={String(days)}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            next.set("days", e.target.value);
            setParams(next, { replace: true });
          }}
          aria-label="Reporting window"
          className={input}
        >
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 90 days</option>
        </select>
      </div>

      {query.isLoading && <Loading what="coverage" />}
      {query.error && (
        <ErrorNote
          error={query.error}
          fallback="Could not load coverage."
          onRetry={() => void query.refetch()}
        />
      )}

      {data && data.total_alerts === 0 && (
        <Empty
          title="No alerts in this window."
          hint="Widen the window, or check that the client's integration is delivering."
        />
      )}

      {data && data.total_alerts > 0 && (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <div className="rounded-lg border border-line bg-ink-800 p-4">
              <p className="text-sm text-dim">Alerts</p>
              <p className="data mt-2 text-2xl">{data.total_alerts.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border border-line bg-ink-800 p-4">
              <p className="text-sm text-dim">Techniques seen</p>
              <p className="data mt-2 text-2xl">{data.techniques.length}</p>
            </div>
            <div className="rounded-lg border border-line bg-ink-800 p-4">
              <p className="text-sm text-dim">Unmapped alerts</p>
              <p className="data mt-2 text-2xl">
                {data.unmapped_alerts.toLocaleString()}
              </p>
              <p className="mt-1 text-xs text-dim">
                {Math.round((data.unmapped_alerts / data.total_alerts) * 100)}% of alerts
                carry no ATT&amp;CK mapping from the rule that fired.
              </p>
            </div>
          </div>

          {data.tactics.length > 0 && (
            <section className="mt-8">
              <h2 className="text-sm font-medium">Tactics</h2>
              <div className="mt-3 space-y-2">
                {data.tactics.map((tactic) => (
                  <div key={tactic.tactic} className="flex items-center gap-3">
                    <span className="w-48 shrink-0 text-sm">{tactic.tactic}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded bg-ink-800">
                      <div
                        className="h-full rounded bg-accent"
                        style={{
                          width: `${maxAlerts ? (tactic.alert_count / maxAlerts) * 100 : 0}%`,
                        }}
                      />
                    </div>
                    <span className="data w-28 shrink-0 text-right text-xs text-dim">
                      {tactic.alert_count.toLocaleString()} alerts
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="mt-8">
            <h2 className="text-sm font-medium">Techniques</h2>
            {data.techniques.length === 0 ? (
              <Empty
                title="No alert in this window carried an ATT&CK technique."
                hint="Wazuh only maps a subset of its ruleset to ATT&CK. A busy console with no techniques usually means the alerts are coming from rules that carry no mapping."
              />
            ) : (
              <div className="mt-3 overflow-x-auto rounded-lg border border-line">
                <table className="w-full min-w-[44rem] border-collapse text-sm">
                  <thead className="sticky top-0 z-10 bg-ink-800">
                    <tr className="border-b border-line text-left text-dim">
                      <th className="px-3 py-2 text-xs font-medium">Technique</th>
                      <th className="px-3 py-2 text-xs font-medium">Peak level</th>
                      <th className="px-3 py-2 text-xs font-medium">Alerts</th>
                      <th className="px-3 py-2 text-xs font-medium">Incidents</th>
                      <th className="px-3 py-2 text-xs font-medium">Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.techniques.map((technique) => (
                      <tr
                        key={technique.technique_id}
                        className="border-b border-line transition last:border-b-0 hover:bg-ink-800"
                      >
                        <td className="data px-3 py-1.5">
                          <a
                            href={`https://attack.mitre.org/techniques/${technique.technique_id.replace(".", "/")}/`}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="transition hover:text-accent"
                          >
                            {technique.technique_id}
                          </a>
                        </td>
                        <td className="px-3 py-1.5">
                          <SeverityChip level={technique.max_severity} />
                        </td>
                        <td className="data px-3 py-1.5 text-xs text-dim">
                          {technique.alert_count.toLocaleString()}
                        </td>
                        <td className="data px-3 py-1.5 text-xs text-dim">
                          {technique.incident_count}
                        </td>
                        <td className="data px-3 py-1.5 text-xs text-dim">
                          {technique.last_seen ? relative(technique.last_seen) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <p className="mt-6 text-xs text-dim">
            Tactic and technique counts are computed independently. Wazuh sends them as
            two separate arrays on an alert rather than as pairs, so a tactic&rsquo;s
            technique count is an approximation, not a join.{" "}
            <Link to="/alerts" className="underline transition hover:text-text">
              Inspect the alerts
            </Link>{" "}
            if a number looks wrong.
          </p>
        </>
      )}
    </div>
  );
}
