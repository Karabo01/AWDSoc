import { useState } from "react";

import { useAuth } from "@/hooks/useAuth";

/** Staff only. Switching clients reissues the token - there is no tenant
 *  parameter anywhere in the API, so this is a real re-auth, not a filter. */
export function TenantSwitcher() {
  const { user, switchTenant } = useAuth();
  const [busy, setBusy] = useState(false);

  if (!user?.is_staff) return null;

  const active = user.tenants.find((t) => t.id === user.active_tenant);

  async function onChange(value: string) {
    setBusy(true);
    try {
      await switchTenant(value === "all" ? null : value);
    } finally {
      setBusy(false);
    }
  }

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="sr-only">Client</span>
      <span
        aria-hidden
        className="h-4 w-[3px] rounded-sm"
        style={{ background: active?.colour ?? "var(--line)" }}
      />
      <select
        value={user.active_tenant ?? "all"}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-line bg-ink-800 px-2 py-1 text-sm outline-none transition focus:border-accent disabled:opacity-60"
      >
        <option value="all">All clients</option>
        {user.tenants.map((tenant) => (
          <option key={tenant.id} value={tenant.id}>
            {tenant.name}
          </option>
        ))}
      </select>
    </label>
  );
}
