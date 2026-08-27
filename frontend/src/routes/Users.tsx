import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type UserCreated, createUser, listUsers, resetPassword, updateUser } from "@/api/users";
import type { Role } from "@/api/types";
import { listTenants } from "@/api/tenants";
import { CopyField } from "@/components/CopyField";
import { Empty, ErrorNote, Loading, relative } from "@/components/States";
import { useAuth } from "@/hooks/useAuth";

const input =
  "rounded border border-line bg-ink-900 px-2 py-1 text-sm outline-none transition focus:border-accent";

const ROLE_LABELS: Record<Role, string> = {
  platform_admin: "Platform admin",
  soc_analyst: "SOC analyst",
  client_admin: "Client admin",
  client_viewer: "Client viewer",
};

const STAFF_ROLES: Role[] = ["platform_admin", "soc_analyst"];
const CLIENT_ROLES: Role[] = ["client_admin", "client_viewer"];

export function Users() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isPlatformAdmin = user?.role === "platform_admin";

  const [includeInactive, setIncludeInactive] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<{
    email: string;
    full_name: string;
    role: Role;
    tenant_id: string;
  }>({ email: "", full_name: "", role: "client_viewer", tenant_id: "" });
  // Shown once, then gone. There is no endpoint that reads it back.
  const [revealed, setRevealed] = useState<UserCreated | null>(null);

  const users = useQuery({
    queryKey: ["users", includeInactive],
    queryFn: () => listUsers(includeInactive),
  });

  const tenants = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
    enabled: isPlatformAdmin,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: () =>
      createUser({
        email: form.email.trim(),
        full_name: form.full_name.trim(),
        role: form.role,
        tenant_id: STAFF_ROLES.includes(form.role) ? null : form.tenant_id || null,
      }),
    onSuccess: (result) => {
      setRevealed(result);
      setCreating(false);
      setForm({ email: "", full_name: "", role: "client_viewer", tenant_id: "" });
      void invalidate();
    },
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      updateUser(id, { is_active }),
    onSuccess: invalidate,
  });

  const reset = useMutation({
    mutationFn: (id: string) => resetPassword(id),
    onSuccess: (result) => setRevealed(result),
  });

  const roles = isPlatformAdmin ? [...STAFF_ROLES, ...CLIENT_ROLES] : CLIENT_ROLES;
  const needsTenant = !STAFF_ROLES.includes(form.role);

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Users</h1>
        <button
          onClick={() => setCreating((open) => !open)}
          className="rounded border border-line px-3 py-1.5 text-sm transition hover:text-accent"
        >
          {creating ? "Cancel" : "Add user"}
        </button>
      </div>

      {!isPlatformAdmin && (
        <p className="mt-1 text-xs text-dim">
          You can manage users in your own organisation only.
        </p>
      )}

      {revealed?.password && (
        <div className="mt-4 rounded-lg border border-accent bg-ink-800 p-4">
          <p className="text-sm font-medium">
            Password for {revealed.user.full_name} ({revealed.user.email})
          </p>
          <p className="mt-1 text-xs text-dim">
            This is shown once and cannot be read back. Send it to them over a channel
            you trust, then close this. Resetting is the only recovery.
          </p>
          <div className="mt-3">
            <CopyField label="Password" value={revealed.password} />
          </div>
          <button
            onClick={() => setRevealed(null)}
            className="mt-3 rounded border border-line px-3 py-1.5 text-sm text-dim transition hover:text-text"
          >
            I have saved it
          </button>
        </div>
      )}

      {creating && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
          className="mt-4 rounded-lg border border-line bg-ink-800 p-4"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              <span className="text-dim">Full name</span>
              <input
                required
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                className={`${input} mt-1 w-full`}
              />
            </label>
            <label className="text-sm">
              <span className="text-dim">Email</span>
              <input
                required
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className={`${input} mt-1 w-full`}
              />
            </label>
            <label className="text-sm">
              <span className="text-dim">Role</span>
              <select
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
                className={`${input} mt-1 w-full`}
              >
                {roles.map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABELS[role]}
                  </option>
                ))}
              </select>
            </label>
            {isPlatformAdmin && needsTenant && (
              <label className="text-sm">
                <span className="text-dim">Client</span>
                <select
                  required
                  value={form.tenant_id}
                  onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
                  className={`${input} mt-1 w-full`}
                >
                  <option value="">Choose a client…</option>
                  {tenants.data?.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <p className="mt-3 text-xs text-dim">
            {STAFF_ROLES.includes(form.role)
              ? "A staff role sees every client it is granted access to and is not tied to one."
              : "A client role is fixed to one client and can never see another."}{" "}
            A password is generated and shown once.
          </p>

          {create.error && (
            <ErrorNote error={create.error} fallback="Could not create that user." />
          )}

          <button
            type="submit"
            disabled={create.isPending}
            className="mt-3 rounded border border-line px-3 py-1.5 text-sm transition hover:text-accent disabled:opacity-60"
          >
            {create.isPending ? "Creating…" : "Create user"}
          </button>
        </form>
      )}

      <label className="mt-4 flex items-center gap-2 text-sm text-dim">
        <input
          type="checkbox"
          checked={includeInactive}
          onChange={(e) => setIncludeInactive(e.target.checked)}
        />
        Show deactivated accounts
      </label>

      {users.isLoading && <Loading what="users" />}
      {users.error && (
        <ErrorNote
          error={users.error}
          fallback="Could not load users."
          onRetry={() => void users.refetch()}
        />
      )}
      {users.data?.length === 0 && <Empty title="No users." />}

      {users.data && users.data.length > 0 && (
        <div className="mt-4 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[44rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-dim">
                <th className="px-3 py-2 font-normal">Name</th>
                <th className="px-3 py-2 font-normal">Email</th>
                <th className="px-3 py-2 font-normal">Role</th>
                {isPlatformAdmin && <th className="px-3 py-2 font-normal">Client</th>}
                <th className="px-3 py-2 font-normal">Last sign-in</th>
                <th className="px-3 py-2 font-normal" />
              </tr>
            </thead>
            <tbody>
              {users.data.map((row) => {
                const self = row.id === user?.id;
                return (
                  <tr
                    key={row.id}
                    className={`border-b border-line last:border-b-0 ${
                      row.is_active ? "" : "opacity-50"
                    }`}
                  >
                    <td className="px-3 py-2">
                      {row.full_name}
                      {self && <span className="ml-2 text-xs text-dim">you</span>}
                    </td>
                    <td className="data px-3 py-2 text-xs text-dim">{row.email}</td>
                    <td className="px-3 py-2 text-xs">{ROLE_LABELS[row.role]}</td>
                    {isPlatformAdmin && (
                      <td className="px-3 py-2 text-xs text-dim">
                        {row.tenant_name ?? "AWDTECH"}
                      </td>
                    )}
                    <td className="data px-3 py-2 text-xs text-dim">
                      {row.last_login_at ? relative(row.last_login_at) : "never"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => reset.mutate(row.id)}
                        disabled={reset.isPending}
                        className="text-xs text-dim underline transition hover:text-text disabled:opacity-50"
                      >
                        Reset password
                      </button>
                      {/* Deactivating yourself is how an estate ends up with no
                          administrator, so the control is not offered at all. */}
                      {!self && (
                        <button
                          onClick={() =>
                            toggleActive.mutate({
                              id: row.id,
                              is_active: !row.is_active,
                            })
                          }
                          className="ml-3 text-xs text-dim underline transition hover:text-text"
                        >
                          {row.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
