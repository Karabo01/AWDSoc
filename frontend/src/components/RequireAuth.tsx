import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import type { Role } from "@/api/types";

export function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { user, status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return <p className="p-6 text-sm text-dim">Checking your session…</p>;
  }
  if (status === "anonymous" || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (roles && !roles.includes(user.role)) {
    return (
      <p className="p-6 text-sm text-dim">
        Your role does not have access to this page.
      </p>
    );
  }
  return <>{children}</>;
}
