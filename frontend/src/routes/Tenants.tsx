import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/api/client";
import {
  type ConnectionCheckResult,
  type SlaBand,
  type Tenant,
  type TenantCreatePayload,
  type TenantSecretRevealed,
  createTenant,
  listTenants,
  putSla,
  rotateSecret,
  testConnection,
  updateTenant,
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

/** Everything about a client that is changeable after onboarding.
 *
 *  The Manager API connection lives here rather than only on the create form
 *  because the common case is onboarding a client first and wiring the manager
 *  later — the ingest push works without it, and only agent sync, rule lookups
 *  and coverage need it.
 *
 *  The password field is write-only in both directions: the API never returns
 *  one, and leaving this box empty leaves the stored credential alone. That is
 *  why it is not pre-filled, and why it says so. */
function EditPanel({ tenant, onDone }: { tenant: Tenant; onDone: () => void }) {
  const queryClient = useQueryClient();
  const existing = tenant.connection;

  const [form, setForm] = useState({
    name: tenant.name,
    status: tenant.status,
    alert_floor: tenant.alert_floor,
    grouping_window_minutes: tenant.grouping_window_minutes,
    colour: tenant.colour ?? "",
    cidrs: tenant.ingest_cidrs.join(", "),
  });

  const [connection, setConnection] = useState({
    base_url: existing?.base_url ?? "",
    username: existing?.username ?? "",
    password: "",
    verify_ssl: existing?.verify_ssl ?? false,
    agent_group: existing?.agent_group ?? "",
  });

  const [bands, setBands] = useState<SlaBand[]>(tenant.sla?.bands ?? []);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        name: form.name,
        status: form.status,
        alert_floor: Number(form.alert_floor),
        grouping_window_minutes: Number(form.grouping_window_minutes),
        colour: form.colour || null,
        ingest_cidrs: form.cidrs
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      };

      // Only send the connection when there is something to send. A first
      // connection needs all three fields; an edit may be just the group.
      const touched = connection.base_url || connection.username || connection.password;
      if (touched) {
        body.connection = {
          base_url: connection.base_url || null,
          username: connection.username || null,
          // Omitted means "leave the stored credential alone".
          password: connection.password || null,
          verify_ssl: connection.verify_ssl,
          agent_group: connection.agent_group.trim() || null,
        };
      }

      await updateTenant(tenant.id, body);
      // Separate endpoint because PUT replaces the whole policy — there is no
      // partial edit of a band list, by design.
      await putSla(tenant.id, { bands });
    },
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["tenants"] });
      onDone();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not save that."),
  });

  return (
    <div className="mt-3 rounded border border-line bg-ink-900 p-4">
      <p className="text-sm font-medium">Client settings</p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className={label}>
          Name
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={input}
          />
        </label>
        <label className={label}>
          Status
          <select
            value={form.status}
            onChange={(e) =>
              setForm({ ...form, status: e.target.value as Tenant["status"] })
            }
            className={input}
          >
            <option value="active">active</option>
            <option value="suspended">suspended</option>
            <option value="offboarding">offboarding</option>
          </select>
        </label>
        <label className={label}>
          Alert floor
          <input
            type="number"
            min={0}
            max={15}
            value={form.alert_floor}
            onChange={(e) => setForm({ ...form, alert_floor: Number(e.target.value) })}
            className={input}
          />
          <span className="mt-1 block text-xs text-dim">
            Display only. The real filter is the{" "}
            <span className="data">&lt;level&gt;</span> in their integration block —
            changing it here does not change what their manager sends.
          </span>
        </label>
        <label className={label}>
          Grouping window (minutes)
          <input
            type="number"
            min={1}
            max={1440}
            value={form.grouping_window_minutes}
            onChange={(e) =>
              setForm({ ...form, grouping_window_minutes: Number(e.target.value) })
            }
            className={input}
          />
        </label>
        <label className={label}>
          Ingest CIDRs
          <input
            value={form.cidrs}
            onChange={(e) => setForm({ ...form, cidrs: e.target.value })}
            placeholder="41.0.0.1/32, 102.0.0.1/32"
            className={`${input} data`}
          />
          <span className="mt-1 block text-xs text-dim">
            Comma separated. Empty means any address may post — fine while testing,
            not in production.
          </span>
        </label>
        <label className={label}>
          Colour
          <input
            value={form.colour}
            onChange={(e) => setForm({ ...form, colour: e.target.value })}
            placeholder="#3b82f6"
            className={`${input} data`}
          />
        </label>
      </div>

      <p className="mt-5 text-sm font-medium">Wazuh Manager API</p>
      <p className="mt-1 max-w-prose text-xs text-dim">
        Read-only — the console never writes to Wazuh. Needed for agent sync, rule
        lookups and coverage. Alert delivery does not depend on it.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className={label}>
          Base URL
          <input
            value={connection.base_url}
            onChange={(e) => setConnection({ ...connection, base_url: e.target.value })}
            placeholder="https://wazuh.example.co.za:55000"
            className={`${input} data`}
          />
        </label>
        <label className={label}>
          Agent group
          <input
            value={connection.agent_group}
            onChange={(e) =>
              setConnection({ ...connection, agent_group: e.target.value })
            }
            placeholder="acme"
            className={`${input} data`}
          />
          <span className="mt-1 block text-xs text-dim">
            On a shared manager this is the tenant boundary. Leave it empty only if
            this client has the manager to themselves — empty means every agent on it
            is listed as theirs.
          </span>
        </label>
        <label className={label}>
          Username
          <input
            value={connection.username}
            onChange={(e) => setConnection({ ...connection, username: e.target.value })}
            autoComplete="off"
            className={input}
          />
        </label>
        <label className={label}>
          Password
          <input
            type="password"
            value={connection.password}
            onChange={(e) => setConnection({ ...connection, password: e.target.value })}
            autoComplete="new-password"
            placeholder={existing ? "unchanged" : ""}
            className={input}
          />
          <span className="mt-1 block text-xs text-dim">
            {existing
              ? "Leave empty to keep the stored password. It cannot be read back."
              : "Stored encrypted. It is never returned by the API."}
          </span>
        </label>
      </div>

      <label className="mt-3 flex flex-wrap items-center gap-2 text-sm text-dim">
        <input
          type="checkbox"
          checked={connection.verify_ssl}
          onChange={(e) => setConnection({ ...connection, verify_ssl: e.target.checked })}
        />
        Verify TLS certificate
        <span className="text-xs">
          (off for the self-signed certificate a default Wazuh install ships with)
        </span>
      </label>

      <p className="mt-5 text-sm font-medium">SLA policy</p>
      <p className="mt-1 max-w-prose text-xs text-dim">
        The band with the highest floor at or below an incident&rsquo;s severity wins.
        No bands means no SLA and no countdown. Higher severity must be tighter, and
        the clock stops while a case is awaiting the client.
      </p>

      <div className="mt-3 space-y-2">
        {bands.map((band, index) => (
          <div key={index} className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-dim">
              Severity &ge;
              <input
                type="number"
                min={0}
                max={15}
                value={band.severity_min}
                onChange={(e) => {
                  const next = [...bands];
                  next[index] = { ...band, severity_min: Number(e.target.value) };
                  setBands(next);
                }}
                className={`${input} w-20`}
              />
            </label>
            <label className="text-xs text-dim">
              Respond (min)
              <input
                type="number"
                min={1}
                value={band.respond_minutes}
                onChange={(e) => {
                  const next = [...bands];
                  next[index] = { ...band, respond_minutes: Number(e.target.value) };
                  setBands(next);
                }}
                className={`${input} w-28`}
              />
            </label>
            <label className="text-xs text-dim">
              Resolve (min)
              <input
                type="number"
                min={1}
                value={band.resolve_minutes}
                onChange={(e) => {
                  const next = [...bands];
                  next[index] = { ...band, resolve_minutes: Number(e.target.value) };
                  setBands(next);
                }}
                className={`${input} w-28`}
              />
            </label>
            <button
              type="button"
              onClick={() => setBands(bands.filter((_, i) => i !== index))}
              className="rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            setBands([
              ...bands,
              { severity_min: 7, respond_minutes: 240, resolve_minutes: 1440 },
            ])
          }
          className="rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text"
        >
          Add band
        </button>
      </div>

      {error && <p className="mt-3 text-sm text-[color:var(--sev-crit)]">{error}</p>}

      <div className="mt-5 flex gap-2">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button
          onClick={onDone}
          className="rounded border border-line px-3 py-1.5 text-sm text-dim transition hover:text-text"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}


function TenantRow({ tenant }: { tenant: Tenant }) {
  const queryClient = useQueryClient();
  const [check, setCheck] = useState<ConnectionCheckResult | null>(null);
  const [revealed, setRevealed] = useState<TenantSecretRevealed | null>(null);
  const [confirmingRotate, setConfirmingRotate] = useState(false);
  const [editing, setEditing] = useState(false);

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
        {editing && <EditPanel tenant={tenant} onDone={() => setEditing(false)} />}
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

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setEditing((open) => !open)}
          className="rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text"
        >
          {editing ? "Close" : "Edit"}
        </button>
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
