import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

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

// Both admin roles manage users and read their own audit trail.
const SETTINGS_NAV = [
  { to: "/settings/users", label: "Users", end: false },
  { to: "/settings/audit", label: "Audit", end: false },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm transition ${
    isActive ? "bg-ink-700 text-accent" : "text-dim hover:text-text"
  }`;

export function AppShell() {
  const { user, signOut } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  // A left-open menu covering the page after navigation is the classic mobile
  // nav bug; closing on route change is the whole fix.
  useEffect(() => setMenuOpen(false), [location.pathname]);

  const items = [
    ...NAV,
    ...(user?.role === "platform_admin" ? ADMIN_NAV : []),
    ...(user?.role === "platform_admin" || user?.role === "client_admin"
      ? SETTINGS_NAV
      : []),
  ];

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-ink-800 px-4">
        <span className="text-sm font-semibold tracking-tight">AWDTECH SOC</span>

        {/* Wide screens get the full bar; narrow ones get the sheet below. */}
        <nav className="hidden items-center gap-1 lg:flex">
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <TenantSwitcher />
          <span className="hidden text-sm text-dim sm:inline">{user?.full_name}</span>
          <button
            onClick={() => void signOut()}
            className="hidden rounded border border-line px-2 py-1 text-sm text-dim transition hover:text-text sm:block"
          >
            Sign out
          </button>
          <button
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            aria-label="Menu"
            className="rounded border border-line px-2 py-1 text-sm text-dim transition hover:text-text lg:hidden"
          >
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
      </header>

      {menuOpen && (
        <nav
          id="mobile-nav"
          className="flex flex-col border-b border-line bg-ink-800 px-2 py-2 lg:hidden"
        >
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
              {item.label}
            </NavLink>
          ))}
          <button
            onClick={() => void signOut()}
            className="mt-1 rounded px-3 py-1.5 text-left text-sm text-dim transition hover:text-text"
          >
            Sign out
          </button>
        </nav>
      )}

      <main className="flex-1 px-3 py-6 sm:px-4">
        <Outlet />
      </main>
    </div>
  );
}
