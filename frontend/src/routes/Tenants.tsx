import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/api/client";
import {
  type ConnectionCheckResult,
  type Tenant,
  type TenantCreatePayload,
  type TenantSecretRevealed,
  createTenant,
  listTenants,
  rotateSecret,
  testConnection,
} from "@/api/tenants";
import { SecretReveal } from "@/components/SecretReveal";

const input =
  "mt-1 w-full rounded border border-line bg-ink-900 px-3 py-2 text-sm outline-none transition focus:border-accent";
const label = "block text-sm text-dim";

function CheckResult({ result }: { result: ConnectionCheckResult }) {
  return (
    <div className="mt-3 rounded border border-line bg-ink-900 p-3 text-sm">
      <p className={result.ok ? "text-[color:var(--sev-low)]" : "text-[color:var(--sev-crit)]"}>
        {result.ok ? "Reachable" : "Not reachable"}
      </p>
      {result.error && <p className="mt-1 text-dim">{result.error}</p>}
      {result.ok && (
        <p className="data mt-1 text-xs text-dim">
          {result.manager_version} · {result.node_name} · {result.agent_count} agents
          {result.agent_group !== null &&
            ` · group ${result.agent_group} (${result.agent_group_count ?? 0})`}
        </p>
      )}
      {result.warnings.map((warning) => (
        <p key={warning} className="mt-1 text-xs text-[color:var(--sev-med)]">
          {warning}
        </p>
      ))}
    </div>
  );
}

function TenantRow({ tenant }: { tenant: Tenant }) {
  const queryClient = useQueryClient();
  const [check, setCheck] = useState<ConnectionCheckResult | null>(null);
  const [revealed, setRevealed] = useState<TenantSecretRevealed | null>(null);
  const [confirmingRotate, setConfirmingRotate] = useState(false);

  const test = useMutation({
    mutationFn: () => testConnection(tenant.id),
    onSuccess: setCheck,
  });
  const rotate = useMutation({
    mutationFn: () => rotateSecret(tenant.id),
    onSuccess: (result) => {
      setRevealed(result);
      setConfirmingRotate(false);
      void queryClient.invalidateQueries({ queryKey: ["tenants"] });
    },
  });

  if (revealed) {
    return (
      <div className="border-b border-line py-4">
        <SecretReveal revealed={revealed} onDone={() => setRevealed(null)} />
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-start gap-4 border-b border-line py-4">
      <span
        aria-hidden
        className="mt-1 h-8 w-[3px] shrink-0 rounded-sm"
        style={{ background: tenant.colour ?? "var(--line)" }}
      />
      <div className="min-w-56 flex-1">
        <p className="font-medium">{tenant.name}</p>
        <p className="data mt-0.5 text-xs text-dim">
          {tenant.slug} · level ≥ {tenant.alert_floor} · {tenant.grouping_window_minutes}m
          window
          {tenant.status !== "active" && ` · ${tenant.status}`}
        </p>
        <p className="data mt-0.5 text-xs text-dim">
          {tenant.connection
            ? `${tenant.connection.base_url}${
                tenant.connection.agent_group
                  ? ` · group ${tenant.connection.agent_group}`
                  : " · no group (dedicated)"
              }`
            : "No Wazuh connection configured"}
        </p>
        {tenant.sla && tenant.sla.bands.length > 0 && (
          <p className="data mt-0.5 text-xs text-dim">
            SLA{" "}
            {tenant.sla.bands
              .map((b) => `≥${b.severity_min}: ${b.respond_minutes}m`)
              .join(" · ")}
          </p>
        )}
        {check && <CheckResult result={check} />}
        {confirmingRotate && (
          <div className="mt-3 rounded border border-line bg-ink-900 p-3 text-sm">
            <p>
              Rotating stops the current secret immediately. This client&rsquo;s alerts
              will fail to deliver until the new block is installed on their manager.
            </p>
            <div className="mt-2 flex gap-2">
              <button
                onClick={() => rotate.mutate()}
                disabled={rotate.isPending}
                className="rounded bg-accent px-2 py-1 text-xs font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
              >
                {rotate.isPending ? "Rotating…" : "Rotate anyway"}
              </button>
              <button
                onClick={() => setConfirmingRotate(false)}
                className="rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text"
              >
                Keep the current secret
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => test.mutate()}
          disabled={test.isPending || !tenant.connection}
          className="rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text disabled:opacity-40"
        >
          {test.isPending ? "Testing…" : "Test connection"}
        </button>
        <button
          onClick={() => setConfirmingRotate(true)}
          className="rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text"
        >
          Rotate secret
        </button>
      </div>
    </div>
  );
}

const EMPTY: TenantCreatePayload = {
  slug: "",
  name: "",
  alert_floor: 7,
  grouping_window_minutes: 30,
  ingest_cidrs: [],
};

function CreateForm({ onCreated }: { onCreated: (r: TenantSecretRevealed) => void }) {
  const [form, setForm] = useState<TenantCreatePayload>(EMPTY);
  const [cidrs, setCidrs] = useState("");
  const [withConnection, setWithConnection] = useState(true);
  const [connection, setConnection] = useState({
    base_url: "",
    username: "",
    password: "",
    verify_ssl: true,
    agent_group: "",
  });
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: createTenant,
    onSuccess: onCreated,
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not create the client."),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    create.mutate({
      ...form,
      ingest_cidrs: cidrs
        .split(/[\s,]+/)
        .map((c) => c.trim())
        .filter(Boolean),
      connection: withConnection
        ? { ...connection, agent_group: connection.agent_group.trim() || null }
        : undefined,
    });
  }

  return (
    <form onSubmit={onSubmit} className="rounded-lg border border-line bg-ink-800 p-6">
      <h2 className="text-base font-semibold">Onboard a client</h2>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <label className={label} htmlFor="name">
            Client name
          </label>
          <input
            id="name"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={input}
          />
        </div>
        <div>
          <label className={label} htmlFor="slug">
            Slug
          </label>
          <input
            id="slug"
            required
            value={form.slug}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
            className={`${input} data`}
          />
          <p className="mt-1 text-xs text-dim">
            Appears in the ingest URL. Lowercase letters, digits and hyphens.
          </p>
        </div>
        <div>
          <label className={label} htmlFor="floor">
            Alert floor
          </label>
          <input
            id="floor"
            type="number"
            min={0}
            max={15}
            value={form.alert_floor}
            onChange={(e) => setForm({ ...form, alert_floor: Number(e.target.value) })}
            className={`${input} data`}
          />
          <p className="mt-1 text-xs text-dim">
            Set in their integration block too, so quieter alerts never leave their
            manager.
          </p>
        </div>
        <div>
          <label className={label} htmlFor="window">
            Grouping window (minutes)
          </label>
          <input
            id="window"
            type="number"
            min={1}
            max={1440}
            value={form.grouping_window_minutes}
            onChange={(e) =>
              setForm({ ...form, grouping_window_minutes: Number(e.target.value) })
            }
            className={`${input} data`}
          />
        </div>
        <div className="sm:col-span-2">
          <label className={label} htmlFor="cidrs">
            Manager egress addresses
          </label>
          <input
            id="cidrs"
            value={cidrs}
            onChange={(e) => setCidrs(e.target.value)}
            placeholder="41.1.2.0/24, 2001:db8::/32"
            className={`${input} data`}
          />
          <p className="mt-1 text-xs text-dim">
            Only these addresses may post alerts for this client. Leave empty to allow
            any source.
          </p>
        </div>
      </div>

      <label className="mt-6 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={withConnection}
          onChange={(e) => setWithConnection(e.target.checked)}
        />
        Configure the Manager API connection now
      </label>

      {withConnection && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className={label} htmlFor="base_url">
              Manager API URL
            </label>
            <input
              id="base_url"
              required
              placeholder="https://wazuh.client.co.za"
              value={connection.base_url}
              onChange={(e) => setConnection({ ...connection, base_url: e.target.value })}
              className={`${input} data`}
            />
          </div>
          <div>
            <label className={label} htmlFor="group">
              Agent group
            </label>
            <input
              id="group"
              value={connection.agent_group}
              onChange={(e) =>
                setConnection({ ...connection, agent_group: e.target.value })
              }
              className={`${input} data`}
            />
            <p className="mt-1 text-xs text-dim">
              Required on a shared manager. It is the only thing routing this
              client&rsquo;s alerts to this client.
            </p>
          </div>
          <div>
            <label className={label} htmlFor="username">
              API user
            </label>
            <input
              id="username"
              required
              value={connection.username}
              onChange={(e) => setConnection({ ...connection, username: e.target.value })}
              className={`${input} data`}
            />
            <p className="mt-1 text-xs text-dim">
              Read-only RBAC. Never reuse <span className="data">wazuh-wui</span>.
            </p>
          </div>
          <div>
            <label className={label} htmlFor="password">
              API password
            </label>
            <input
              id="password"
              type="password"
              required
              value={connection.password}
              onChange={(e) => setConnection({ ...connection, password: e.target.value })}
              className={input}
            />
            <p className="mt-1 text-xs text-dim">
              Encrypted at rest and never returned by the API.
            </p>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-4 text-sm text-[color:var(--sev-crit)]">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={create.isPending}
        className="mt-6 rounded bg-accent px-3 py-2 text-sm font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
      >
        {create.isPending ? "Onboarding…" : "Onboard client"}
      </button>
    </form>
  );
}

export function Tenants() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [revealed, setRevealed] = useState<TenantSecretRevealed | null>(null);
  const { data: tenants, isLoading, error } = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
  });

  return (
    <div className="mx-auto max-w-4xl">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Clients</h1>
        {!creating && !revealed && (
          <button
            onClick={() => setCreating(true)}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-ink-900 transition hover:brightness-110"
          >
            Onboard a client
          </button>
        )}
      </div>

      {revealed && (
        <div className="mt-6">
          <SecretReveal
            revealed={revealed}
            onDone={() => {
              setRevealed(null);
              void queryClient.invalidateQueries({ queryKey: ["tenants"] });
            }}
          />
        </div>
      )}

      {creating && !revealed && (
        <div className="mt-6">
          <CreateForm
            onCreated={(result) => {
              setRevealed(result);
              setCreating(false);
            }}
          />
          <button
            onClick={() => setCreating(false)}
            className="mt-3 text-sm text-dim transition hover:text-text"
          >
            Cancel
          </button>
        </div>
      )}

      <div className="mt-8">
        {isLoading && <p className="text-sm text-dim">Loading clients…</p>}
        {error && (
          <p className="text-sm text-[color:var(--sev-crit)]">
            {error instanceof ApiError ? error.message : "Could not load clients."}
          </p>
        )}
        {tenants?.length === 0 && !creating && (
          <p className="text-sm text-dim">
            No clients yet. Onboarding one takes a form here and one command on their
            manager.
          </p>
        )}
        {tenants?.map((tenant) => <TenantRow key={tenant.id} tenant={tenant} />)}
      </div>
    </div>
  );
}
