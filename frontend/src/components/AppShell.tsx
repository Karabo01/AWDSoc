import {
  Activity,
  AlertTriangle,
  Building2,
  ChevronLeft,
  FileClock,
  FileText,
  Fingerprint,
  LayoutGrid,
  Menu,
  MonitorSmartphone,
  Shield,
  Target,
  Users as UsersIcon,
  X,
} from "lucide-react";
import { type ComponentType, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { TenantSwitcher } from "@/components/TenantSwitcher";
import { useAuth } from "@/hooks/useAuth";

interface NavItem {
  to: string;
  label: string;
  end: boolean;
  icon: ComponentType<{ size?: number | string; className?: string }>;
  roles?: string[];
}

interface NavSection {
  heading: string;
  items: NavItem[];
}

/** Grouped like a SIEM console rather than as one flat list: an analyst reaches
 *  for a section before an item, and the grouping is what tells a newcomer that
 *  Coverage is a threat-management view and Agents is a plumbing one. */
const SECTIONS: NavSection[] = [
  {
    heading: "General",
    items: [
      { to: "/", label: "Overview", end: true, icon: LayoutGrid },
      { to: "/incidents", label: "Incidents", end: false, icon: AlertTriangle },
      { to: "/alerts", label: "Alerts", end: false, icon: Activity },
      { to: "/reports", label: "Reports", end: false, icon: FileText },
    ],
  },
  {
    heading: "Threat management",
    items: [
      { to: "/entities", label: "Entities", end: false, icon: Fingerprint },
      { to: "/coverage", label: "MITRE coverage", end: false, icon: Target },
    ],
  },
  {
    heading: "Configuration",
    items: [
      { to: "/agents", label: "Agents", end: false, icon: MonitorSmartphone },
      {
        to: "/settings/tenants",
        label: "Clients",
        end: false,
        icon: Building2,
        roles: ["platform_admin"],
      },
      {
        to: "/settings/users",
        label: "Users",
        end: false,
        icon: UsersIcon,
        roles: ["platform_admin", "client_admin"],
      },
      {
        to: "/settings/audit",
        label: "Audit log",
        end: false,
        icon: FileClock,
        roles: ["platform_admin", "client_admin"],
      },
    ],
  },
];

export function AppShell() {
  const { user, signOut } = useAuth();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Collapsed to icons only. Remembered per browser, because an analyst who
  // wants the width back for a wide grid wants it back tomorrow too.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("awdsoc.rail") === "collapsed";
    } catch {
      return false;
    }
  });

  // A drawer left open over the page after navigating is the classic mobile bug.
  useEffect(() => setDrawerOpen(false), [location.pathname]);

  useEffect(() => {
    try {
      localStorage.setItem("awdsoc.rail", collapsed ? "collapsed" : "expanded");
    } catch {
      /* a private window is not a reason to break the nav */
    }
  }, [collapsed]);

  const visible = SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) => !item.roles || (user?.role && item.roles.includes(user.role)),
    ),
  })).filter((section) => section.items.length > 0);

  const rail = (isCollapsed: boolean) => (
    <nav
      aria-label="Main"
      className={`flex shrink-0 flex-col gap-4 overflow-y-auto border-r border-line bg-ink-800 py-3 transition-[width] ${
        isCollapsed ? "w-14 px-2" : "w-56 px-3"
      }`}
    >
      {visible.map((section) => (
        <div key={section.heading}>
          {!isCollapsed && (
            <p className="px-2 pb-1 text-[11px] uppercase tracking-wide text-dim">
              {section.heading}
            </p>
          )}
          <div className="flex flex-col gap-0.5">
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                title={isCollapsed ? item.label : undefined}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded px-2 py-1.5 text-sm transition ${
                    isCollapsed ? "justify-center" : ""
                  } ${
                    isActive
                      ? // The active marker is a left bar, not a fill: it survives
                        // the collapsed rail, where a fill reads as a button.
                        "bg-ink-700 text-text shadow-[inset_2px_0_0_var(--accent)]"
                      : "text-dim hover:bg-ink-700/60 hover:text-text"
                  }`
                }
              >
                <item.icon size={16} className="shrink-0" />
                {!isCollapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </div>
        </div>
      ))}

      <button
        onClick={() => setCollapsed((open) => !open)}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        className="mt-auto hidden items-center gap-2 rounded px-2 py-1.5 text-xs text-dim transition hover:text-text lg:flex"
      >
        <ChevronLeft
          size={14}
          className={`shrink-0 transition-transform ${collapsed ? "rotate-180" : ""}`}
        />
        {!collapsed && "Collapse"}
      </button>
    </nav>
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-ink-800 px-3">
        <button
          onClick={() => setDrawerOpen((open) => !open)}
          aria-expanded={drawerOpen}
          aria-label="Menu"
          className="rounded p-1.5 text-dim transition hover:text-text lg:hidden"
        >
          {drawerOpen ? <X size={18} /> : <Menu size={18} />}
        </button>

        <span className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <Shield size={16} className="text-accent" />
          AWDTECH SOC
        </span>

        <div className="ml-auto flex items-center gap-3">
          <TenantSwitcher />
          <span className="hidden text-sm text-dim sm:inline">{user?.full_name}</span>
          <button
            onClick={() => void signOut()}
            className="rounded border border-line px-2 py-1 text-xs text-dim transition hover:text-text"
          >
            Sign out
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="hidden lg:flex">{rail(collapsed)}</div>

        {drawerOpen && (
          <>
            <div
              className="fixed inset-0 top-12 z-20 bg-black/50 lg:hidden"
              onClick={() => setDrawerOpen(false)}
              aria-hidden
            />
            <div className="fixed inset-y-0 top-12 z-30 flex lg:hidden">{rail(false)}</div>
          </>
        )}

        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
