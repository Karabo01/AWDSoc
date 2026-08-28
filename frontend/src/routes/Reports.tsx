import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, FilePlus2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  type ReportPayload,
  createReport,
  listReports,
  previewReport,
} from "@/api/reports";
import { Command, CommandBar, CommandDivider } from "@/components/CommandBar";
import { GridHead, GridShell, Th, gridCell } from "@/components/DataGrid";
import { ReportDocument } from "@/components/ReportDocument";
import { Empty, ErrorNote, Loading, relative } from "@/components/States";
import { TenantChip } from "@/components/TenantChip";
import { useAuth } from "@/hooks/useAuth";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

/** Whole calendar months, because that is the unit a client is invoiced in and
 *  the unit they will ask about. An arbitrary range is still possible by editing
 *  the dates; this just makes the common case one click. */
function lastMonths(count: number) {
  const options: { label: string; start: string; end: string }[] = [];
  const now = new Date();
  for (let back = 0; back < count; back += 1) {
    const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - back, 1));
    const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - back + 1, 1));
    options.push({
      label: start.toLocaleDateString(undefined, {
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      }),
      start: start.toISOString().slice(0, 10),
      end: end.toISOString().slice(0, 10),
    });
  }
  return options;
}

function StatusPill({ status }: { status: "draft" | "issued" }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs ${
        status === "issued"
          ? "bg-[rgba(224,163,46,.12)] text-accent"
          : "bg-ink-700 text-dim"
      }`}
    >
      {status === "issued" ? "Issued" : "Draft"}
    </span>
  );
}

export function Reports() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isStaff = user?.is_staff ?? false;
  // A report covers one client, so generating needs a client in scope.
  const scoped = !isStaff || Boolean(user?.active_tenant);

  const months = lastMonths(6);
  const [period, setPeriod] = useState(months[1] ?? months[0]);
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<ReportPayload | null>(null);

  const reports = useQuery({ queryKey: ["reports"], queryFn: listReports });

  const body = () => ({
    period_start: `${period.start}T00:00:00Z`,
    period_end: `${period.end}T00:00:00Z`,
    summary_note: note.trim() || undefined,
  });

  const runPreview = useMutation({
    mutationFn: () => previewReport(body()),
    onSuccess: (result) => setPreview(result.payload),
  });

  const save = useMutation({
    mutationFn: () => createReport(body()),
    onSuccess: (report) => {
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      navigate(`/reports/${report.id}`);
    },
  });

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-base font-semibold">Reports</h1>
      <p className="mt-1 max-w-prose text-xs text-dim">
        A client-facing summary of the period: incidents handled, service levels met,
        and what was detected. Figures are frozen when the report is generated, so what
        you send stays reproducible after the underlying alerts age out.
      </p>

      {isStaff && (
        <section className="mt-5 rounded-lg border border-line bg-ink-800 p-4">
          <p className="text-sm font-medium">Generate</p>

          {!scoped ? (
            <p className="mt-2 max-w-prose text-sm text-dim">
              A report covers one client. Switch to that client with the selector in the
              header, then generate.
            </p>
          ) : (
            <>
              <div className="mt-3 flex flex-wrap items-end gap-3">
                <label className="text-sm">
                  <span className="text-xs text-dim">Period</span>
                  <select
                    value={period.start}
                    onChange={(e) =>
                      setPeriod(
                        months.find((m) => m.start === e.target.value) ?? months[0],
                      )
                    }
                    className={`${input} mt-1 block`}
                  >
                    {months.map((month) => (
                      <option key={month.start} value={month.start}>
                        {month.label}
                      </option>
                    ))}
                  </select>
                </label>

                <button
                  onClick={() => runPreview.mutate()}
                  disabled={runPreview.isPending}
                  className="rounded border border-line px-3 py-1.5 text-sm transition hover:text-accent disabled:opacity-60"
                >
                  {runPreview.isPending ? "Building…" : "Preview"}
                </button>
                <button
                  onClick={() => save.mutate()}
                  disabled={save.isPending}
                  className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
                >
                  {save.isPending ? "Saving…" : "Save as draft"}
                </button>
              </div>

              <label className="mt-3 block text-sm">
                <span className="text-xs text-dim">
                  Covering note — the only prose in the report a person writes
                </span>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={3}
                  placeholder="A quiet month. The two credential-stuffing bursts against the VPN were blocked at the edge and needed no action from your team…"
                  className={`${input} mt-1 w-full`}
                />
              </label>

              {(runPreview.error || save.error) && (
                <ErrorNote
                  error={runPreview.error ?? save.error}
                  fallback="Could not build that report."
                />
              )}
            </>
          )}
        </section>
      )}

      {preview && (
        <section className="mt-6 rounded-lg border border-accent/40 bg-ink-800 p-5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-accent">
              Preview — nothing has been saved
            </p>
            <button
              onClick={() => setPreview(null)}
              className="text-xs text-dim underline transition hover:text-text"
            >
              Close
            </button>
          </div>
          <div className="mt-4">
            <ReportDocument
              payload={preview}
              title={`${preview.tenant?.name ?? "Client"} — ${period.label}`}
              note={note.trim() || null}
            />
          </div>
        </section>
      )}

      <div className="mt-8">
        <CommandBar>
          <Command
            icon={RefreshCw}
            label="Refresh"
            busy={reports.isFetching}
            onClick={() => void reports.refetch()}
          />
          {isStaff && scoped && (
            <>
              <CommandDivider />
              <Command
                icon={Eye}
                label="Preview"
                busy={runPreview.isPending}
                onClick={() => runPreview.mutate()}
              />
              <Command
                icon={FilePlus2}
                label="New draft"
                busy={save.isPending}
                onClick={() => save.mutate()}
              />
            </>
          )}
        </CommandBar>
      </div>

      {reports.isLoading && <Loading what="reports" />}
      {reports.error && (
        <ErrorNote
          error={reports.error}
          fallback="Could not load reports."
          onRetry={() => void reports.refetch()}
        />
      )}

      {reports.data?.length === 0 && (
        <Empty
          title="No reports yet."
          hint={
            isStaff
              ? "Generate one for last month, add a covering note, then issue it — issuing is what makes it visible to the client."
              : "Your provider has not issued a report yet."
          }
        />
      )}

      {reports.data && reports.data.length > 0 && (
        <div className="mt-4">
          <GridShell>
            <table className="w-full min-w-[44rem] border-collapse text-sm">
              <GridHead>
                <Th>#</Th>
                <Th>Report</Th>
                {isStaff && <Th>Client</Th>}
                <Th>Period</Th>
                <Th>Status</Th>
                <Th>Generated</Th>
              </GridHead>
              <tbody>
                {reports.data.map((report) => (
                  <tr
                    key={report.id}
                    onClick={() => navigate(`/reports/${report.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(`/reports/${report.id}`);
                      }
                    }}
                    tabIndex={0}
                    role="link"
                    aria-label={report.title}
                    className="cursor-pointer border-b border-line outline-none transition last:border-b-0 hover:bg-ink-800 focus-visible:bg-ink-800 focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-accent"
                  >
                    <td className={`${gridCell} data text-xs text-dim`}>
                      {report.number}
                    </td>
                    <td className={gridCell}>
                      <Link
                        to={`/reports/${report.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="transition hover:text-accent"
                      >
                        {report.title}
                      </Link>
                    </td>
                    {isStaff && (
                      <td className={gridCell}>
                        <TenantChip name={report.tenant_name} colour={null} />
                      </td>
                    )}
                    <td className={`${gridCell} data text-xs text-dim`}>
                      {new Date(report.period_start).toLocaleDateString(undefined, {
                        month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td className={gridCell}>
                      <StatusPill status={report.status} />
                    </td>
                    <td className={`${gridCell} data text-xs text-dim`}>
                      {relative(report.generated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GridShell>
        </div>
      )}
    </div>
  );
}
