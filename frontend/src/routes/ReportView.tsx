import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Printer, Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  deleteReport,
  getReport,
  issueReport,
  updateReport,
} from "@/api/reports";
import { Command, CommandBar, CommandDivider } from "@/components/CommandBar";
import { ReportDocument } from "@/components/ReportDocument";
import { ErrorNote, Loading } from "@/components/States";
import { useAuth } from "@/hooks/useAuth";

export function ReportView() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isStaff = user?.is_staff ?? false;

  const report = useQuery({
    queryKey: ["report", id],
    queryFn: () => getReport(id),
    enabled: Boolean(id),
  });

  const [note, setNote] = useState("");
  const [title, setTitle] = useState("");
  const [dirty, setDirty] = useState(false);
  const [confirmIssue, setConfirmIssue] = useState(false);

  // Adopt the server's copy only while untouched, so a background refetch cannot
  // overwrite a sentence someone is mid-way through.
  useEffect(() => {
    if (!dirty && report.data) {
      setNote(report.data.summary_note ?? "");
      setTitle(report.data.title);
    }
  }, [report.data, dirty]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["report", id] });
    void queryClient.invalidateQueries({ queryKey: ["reports"] });
  };

  const save = useMutation({
    mutationFn: () => updateReport(id, { title, summary_note: note.trim() || null }),
    onSuccess: () => {
      setDirty(false);
      invalidate();
    },
  });

  const issue = useMutation({
    mutationFn: () => issueReport(id),
    onSuccess: () => {
      setConfirmIssue(false);
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteReport(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      navigate("/reports");
    },
  });

  if (report.isLoading) return <Loading what="report" />;
  if (report.error)
    return (
      <ErrorNote
        error={report.error}
        fallback="Could not load that report."
        onRetry={() => void report.refetch()}
      />
    );
  if (!report.data) return null;

  const data = report.data;
  const isDraft = data.status === "draft";
  const editable = isStaff && isDraft;

  return (
    <div className="mx-auto max-w-4xl">
      <div className="print-hide">
        <Link to="/reports" className="text-sm text-dim transition hover:text-text">
          ← Reports
        </Link>

        <div className="mt-3">
          <CommandBar>
            <Command icon={Printer} label="Print / Save as PDF" onClick={() => window.print()} />
            {isStaff && (
              <>
                <CommandDivider />
                <Command
                  icon={Send}
                  label={isDraft ? "Issue to client" : "Issued"}
                  disabled={!isDraft}
                  busy={issue.isPending}
                  onClick={() => setConfirmIssue(true)}
                />
                {user?.role === "platform_admin" && (
                  <Command
                    icon={Trash2}
                    label="Delete draft"
                    danger
                    disabled={!isDraft}
                    busy={remove.isPending}
                    onClick={() => remove.mutate()}
                  />
                )}
              </>
            )}
            <span className="ml-auto text-xs text-dim">
              {isDraft ? (
                "Draft — not visible to the client"
              ) : (
                <>
                  Issued{" "}
                  {data.issued_at
                    ? new Date(data.issued_at).toLocaleDateString()
                    : ""}{" "}
                  · visible to the client
                </>
              )}
            </span>
          </CommandBar>
        </div>

        {confirmIssue && (
          <div className="mt-3 rounded-lg border border-accent/50 bg-ink-800 p-4 text-sm">
            <p>
              Issuing makes this report visible to{" "}
              <strong>{data.tenant_name}</strong>&rsquo;s users in their own console, and
              freezes its wording. Corrections after this mean generating a new report,
              not editing this one.
            </p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => issue.mutate()}
                disabled={issue.isPending}
                className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
              >
                {issue.isPending ? "Issuing…" : "Issue it"}
              </button>
              <button
                onClick={() => setConfirmIssue(false)}
                className="rounded border border-line px-3 py-1.5 text-sm text-dim transition hover:text-text"
              >
                Keep as draft
              </button>
            </div>
          </div>
        )}

        {(issue.error || remove.error || save.error) && (
          <ErrorNote
            error={issue.error ?? remove.error ?? save.error}
            fallback="That did not work."
          />
        )}

        {editable && (
          <div className="mt-4 rounded-lg border border-line bg-ink-800 p-4">
            <label className="block text-sm">
              <span className="text-xs text-dim">Title</span>
              <input
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                  setDirty(true);
                }}
                className="mt-1 w-full rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent"
              />
            </label>
            <label className="mt-3 block text-sm">
              <span className="text-xs text-dim">
                Covering note — appears at the top of the report
              </span>
              <textarea
                value={note}
                onChange={(e) => {
                  setNote(e.target.value);
                  setDirty(true);
                }}
                rows={4}
                className="mt-1 w-full rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent"
              />
            </label>
            <p className="mt-2 text-xs text-dim">
              The figures below are not editable. A report whose numbers can be typed
              over is not evidence of anything.
            </p>
            <button
              onClick={() => save.mutate()}
              disabled={!dirty || save.isPending}
              className="mt-3 rounded border border-line px-3 py-1.5 text-sm transition hover:text-accent disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        )}
      </div>

      <div className="mt-6 rounded-lg border border-line bg-ink-800 p-6 print:border-0 print:bg-transparent print:p-0">
        <ReportDocument
          payload={data.payload}
          title={dirty ? title : data.title}
          note={dirty ? note : data.summary_note}
        />
      </div>
    </div>
  );
}
