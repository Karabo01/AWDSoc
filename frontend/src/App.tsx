import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { onSessionEnded } from "@/api/client";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useAuth } from "@/hooks/useAuth";
import { AlertDetail } from "@/routes/AlertDetail";
import { Alerts } from "@/routes/Alerts";
import { IncidentDetail } from "@/routes/IncidentDetail";
import { Incidents } from "@/routes/Incidents";
import { Login } from "@/routes/Login";
import { Overview } from "@/routes/Overview";
import { Placeholder } from "@/routes/Placeholder";
import { Tenants } from "@/routes/Tenants";

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
        <Route
          path="/entities"
          element={<Placeholder title="Entities" milestone="M6" />}
        />
        <Route path="/agents" element={<Placeholder title="Agents" milestone="M7" />} />
        <Route
          path="/coverage"
          element={<Placeholder title="MITRE coverage" milestone="M7" />}
        />
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
              <Placeholder title="Users" milestone="M8" />
            </RequireAuth>
          }
        />
        <Route
          path="/settings/audit"
          element={
            <RequireAuth roles={["platform_admin", "client_admin"]}>
              <Placeholder title="Audit log" milestone="M8" />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
