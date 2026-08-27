import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { OverviewTrend } from "@/api/overview";

const AXIS = { stroke: "var(--text-dim)", fontSize: 11 };

const SEVERITY_COLOURS: Record<string, string> = {
  Critical: "var(--sev-crit)",
  High: "var(--sev-high)",
  Medium: "var(--sev-med)",
  Low: "var(--text-dim)",
};

const STATUS_LABELS: Record<string, string> = {
  new: "New",
  active: "Active",
  pending: "Awaiting client",
};

function Panel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-ink-800 p-4">
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="mt-0.5 text-xs text-dim">{hint}</p>}
      <div className="mt-3 h-44">{children}</div>
    </div>
  );
}

/** Recharts' default tooltip is a white card. On a dark console that is a flash
 *  of glare every time the pointer crosses the chart. */
const TOOLTIP = {
  contentStyle: {
    background: "var(--ink-700)",
    border: "1px solid var(--line)",
    borderRadius: 6,
    fontSize: 12,
  },
  labelStyle: { color: "var(--text-dim)" },
  itemStyle: { color: "var(--text)" },
};

export function TrendCharts({ trend }: { trend: OverviewTrend }) {
  const hourly = trend.bucket_hours === 1;

  const points = trend.buckets.map((bucket) => ({
    ...bucket,
    label: new Date(bucket.at).toLocaleString(undefined,
      hourly
        ? { hour: "2-digit", minute: "2-digit" }
        : { month: "short", day: "numeric" },
    ),
  }));

  const severity = trend.by_severity.filter((slice) => slice.count > 0);
  const status = trend.by_status.map((slice) => ({
    ...slice,
    label: STATUS_LABELS[slice.status] ?? slice.status,
  }));

  return (
    <div className="mt-6 grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <Panel
          title="Incidents and alerts"
          hint={
            hourly
              ? "Hourly. Incidents by when they were opened, alerts by when they were detected."
              : "Daily. Incidents by when they were opened, alerts by when they were detected."
          }
        >
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
              <defs>
                <linearGradient id="alertsFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="incidentsFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--sev-high)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--sev-high)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} {...AXIS} />
              {/* Two axes because alert volume is an order of magnitude above
                  incident volume — on one axis the incident line is flat. */}
              <YAxis yAxisId="alerts" tickLine={false} axisLine={false} {...AXIS} />
              <YAxis
                yAxisId="incidents"
                orientation="right"
                tickLine={false}
                axisLine={false}
                {...AXIS}
              />
              <Tooltip {...TOOLTIP} />
              <Area
                yAxisId="alerts"
                type="monotone"
                dataKey="alerts"
                name="Alerts"
                stroke="var(--accent)"
                fill="url(#alertsFill)"
                strokeWidth={1.5}
              />
              <Area
                yAxisId="incidents"
                type="monotone"
                dataKey="incidents"
                name="Incidents"
                stroke="var(--sev-high)"
                fill="url(#incidentsFill)"
                strokeWidth={1.5}
              />
            </AreaChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <Panel title="Open by severity" hint="What is on the board now, not what was opened.">
        {severity.length === 0 ? (
          <p className="flex h-full items-center justify-center text-sm text-dim">
            Nothing open.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={severity}
              layout="vertical"
              margin={{ top: 4, right: 12, bottom: 0, left: 8 }}
            >
              <CartesianGrid stroke="var(--line)" horizontal={false} />
              <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} {...AXIS} />
              <YAxis
                type="category"
                dataKey="label"
                width={62}
                tickLine={false}
                axisLine={false}
                {...AXIS}
              />
              <Tooltip {...TOOLTIP} cursor={{ fill: "var(--ink-700)" }} />
              <Bar dataKey="count" name="Open" radius={[0, 3, 3, 0]}>
                {severity.map((slice) => (
                  <Cell key={slice.label} fill={SEVERITY_COLOURS[slice.label]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </Panel>

      <Panel title="Open by status" hint="Awaiting client is a stopped SLA clock.">
        {status.length === 0 ? (
          <p className="flex h-full items-center justify-center text-sm text-dim">
            Nothing open.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={status} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} {...AXIS} />
              <YAxis tickLine={false} axisLine={false} allowDecimals={false} {...AXIS} />
              <Tooltip {...TOOLTIP} cursor={{ fill: "var(--ink-700)" }} />
              <Bar dataKey="count" name="Open" fill="var(--accent)" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Panel>

      <div className="lg:col-span-2">
        <Panel title="Critical opened" hint="Level 13 and above, in the same window.">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} {...AXIS} />
              <YAxis tickLine={false} axisLine={false} allowDecimals={false} {...AXIS} />
              <Tooltip {...TOOLTIP} cursor={{ fill: "var(--ink-700)" }} />
              <Bar
                dataKey="critical"
                name="Critical"
                fill="var(--sev-crit)"
                radius={[2, 2, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </div>
    </div>
  );
}
