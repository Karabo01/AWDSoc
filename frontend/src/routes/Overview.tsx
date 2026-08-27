import { useQuery } from "@tanstack/react-query";

import { rootGet } from "@/api/client";
import type { Health } from "@/api/types";
import { useAuth } from "@/hooks/useAuth";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-ink-800 p-4">
      <p className="text-sm text-dim">{label}</p>
      <p className="data mt-2 text-2xl">{value}</p>
      {hint && <p className="mt-1 text-xs text-dim">{hint}</p>}
    </div>
  );
}

export function Overview() {
  const { user } = useAuth();
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => rootGet<Health>("/healthz"),
    refetchInterval: 30_000,
  });

  const scope = user?.is_staff
    ? user.active_tenant
      ? (user.tenants.find((t) => t.id === user.active_tenant)?.name ?? "One client")
      : "All clients"
    : "Your environment";

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold">Overview</h1>
      <p className="mt-1 text-sm text-dim">{scope}</p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Open incidents" value="—" hint="Arrives with M5" />
        <Tile label="Alerts today" value="—" hint="Arrives with M3" />
        <Tile label="Clients online" value="—" hint="Arrives with M7" />
        <Tile
          label="Platform"
          value={health ? (health.status === "ok" ? "Healthy" : "Degraded") : "…"}
          hint={
            health
              ? `postgres ${health.postgres.ok ? "up" : "down"} · redis ${
                  health.redis.ok ? "up" : "down"
                } · worker ${health.worker.alive ? "alive" : "quiet"}`
              : undefined
          }
        />
      </div>

      <p className="mt-8 text-sm text-dim">
        Ingest is not wired up yet. Onboard a client and install the integrator on their
        manager to start receiving alerts.
      </p>
    </div>
  );
}
