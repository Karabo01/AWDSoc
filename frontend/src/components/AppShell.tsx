import { NavLink, Outlet } from "react-router-dom";

import { TenantSwitcher } from "@/components/TenantSwitcher";
import { useAuth } from "@/hooks/useAuth";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/incidents", label: "Incidents", end: false },
  { to: "/alerts", label: "Alerts", end: false },
  { to: "/entities", label: "Entities", end: false },
  { to: "/agents", label: "Agents", end: false },
  { to: "/coverage", label: "Coverage", end: false },
];

// platform_admin only; client-facing roles never see tenant management.
const ADMIN_NAV = [{ to: "/settings/tenants", label: "Clients", end: false }];

export function AppShell() {
  const { user, signOut } = useAuth();

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-6 border-b border-line bg-ink-800 px-4">
        <span className="text-sm font-semibold tracking-tight">AWDTECH SOC</span>

        <nav className="flex items-center gap-1">
          {[...NAV, ...(user?.role === "platform_admin" ? ADMIN_NAV : [])].map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded px-3 py-1.5 text-sm transition ${
                  isActive ? "bg-ink-700 text-accent" : "text-dim hover:text-text"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-4">
          <TenantSwitcher />
          <span className="text-sm text-dim">{user?.full_name}</span>
          <button
            onClick={() => void signOut()}
            className="rounded border border-line px-2 py-1 text-sm text-dim transition hover:text-text"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
