import type { ReactNode } from "react";

import { ApiError } from "@/api/client";

/** Empty and error states, in one place so every page says the same kind of
 *  thing in the same voice.
 *
 *  An empty state that only says "no results" wastes the one moment the analyst
 *  is actually looking for guidance. Each one here takes a `hint` naming the
 *  usual cause — an alert floor, a missing integration, a filter still applied. */

export function Loading({ what }: { what: string }) {
  return (
    <p className="mt-6 text-sm text-dim" role="status" aria-live="polite">
      Loading {what}…
    </p>
  );
}

export function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mt-6 rounded-lg border border-dashed border-line px-4 py-8 text-center">
      <p className="text-sm">{title}</p>
      {hint && <p className="mx-auto mt-2 max-w-prose text-sm text-dim">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({
  error,
  fallback,
  onRetry,
}: {
  error: unknown;
  fallback: string;
  onRetry?: () => void;
}) {
  // A 403 is not a failure to load — it is an answer, and saying "could not
  // load" for one sends the reader looking for a fault that is not there.
  const status = error instanceof ApiError ? error.status : undefined;
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : fallback;

  return (
    <div
      role="alert"
      className="mt-6 rounded-lg border border-line bg-ink-800 px-4 py-3 text-sm"
    >
      <p className={status === 403 ? "text-dim" : "text-[color:var(--sev-crit)]"}>
        {message}
      </p>
      {onRetry && status !== 403 && (
        <button
          onClick={onRetry}
          className="mt-2 rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/** A staleness marker for anything read from a cache of someone else's system.
 *  Agent and rule data are projections of a client's manager; an analyst must
 *  never have to guess how old the thing in front of them is. */
export function Freshness({ at, label = "synced" }: { at: string | null; label?: string }) {
  if (!at) return <span className="text-xs text-dim">never {label}</span>;
  const age = Date.now() - new Date(at).getTime();
  const hours = age / 3_600_000;
  const stale = hours > 2;
  return (
    <span
      className={`data text-xs ${stale ? "text-[color:var(--sev-med)]" : "text-dim"}`}
      title={new Date(at).toLocaleString()}
    >
      {label} {relative(at)}
    </span>
  );
}

export function relative(value: string): string {
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
