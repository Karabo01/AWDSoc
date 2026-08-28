import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { onSessionEnded } from "@/api/client";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useAuth } from "@/hooks/useAuth";
import { AgentDetail } from "@/routes/AgentDetail";
import { Agents } from "@/routes/Agents";
import { AlertDetail } from "@/routes/AlertDetail";
import { Alerts } from "@/routes/Alerts";
import { AuditLog } from "@/routes/AuditLog";
import { Coverage } from "@/routes/Coverage";
import { EntityDetail } from "@/routes/EntityDetail";
import { Entities } from "@/routes/Entities";
import { IncidentDetail } from "@/routes/IncidentDetail";
import { Incidents } from "@/routes/Incidents";
import { Login } from "@/routes/Login";
import { Overview } from "@/routes/Overview";
import { ReportView } from "@/routes/ReportView";
import { Reports } from "@/routes/Reports";
import { Tenants } from "@/routes/Tenants";
import { Users } from "@/routes/Users";

export function App() {
  const restore = useAuth((s) => s.restore);

  useEffect(() => {
    void restore();
    onSessionEnded(() => {
      useAuth.setState({ user: null, status: "anonymous" });
    });
  }, [restore]);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Overview />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/incidents/:tenant/:number" element={<IncidentDetail />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/alerts/:id" element={<AlertDetail />} />
        <Route path="/entities" element={<Entities />} />
        {/* An entity value can contain slashes (a file path, a DOMAIN\user), so
            the wildcard mirrors the `{value:path}` parameter on the API. */}
        <Route path="/entities/:type/*" element={<EntityDetail />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/agents/:agentId" element={<AgentDetail />} />
        <Route path="/coverage" element={<Coverage />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/reports/:id" element={<ReportView />} />
        <Route
          path="/settings/tenants"
          element={
            <RequireAuth roles={["platform_admin"]}>
              <Tenants />
            </RequireAuth>
          }
        />
        <Route
          path="/settings/users"
          element={
            <RequireAuth roles={["platform_admin", "client_admin"]}>
              <Users />
            </RequireAuth>
          }
        />
        <Route
          path="/settings/audit"
          element={
            <RequireAuth roles={["platform_admin", "client_admin"]}>
              <AuditLog />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
