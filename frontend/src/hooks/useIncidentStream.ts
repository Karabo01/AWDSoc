import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { getAccessToken, refreshAccessToken } from "@/api/client";

const BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export type StreamState = "connecting" | "live" | "offline";

export interface IncidentEvent {
  kind: "created" | "updated" | "alert";
  tenant_id: string;
  incident_id: string;
  number: number | null;
  severity: number | null;
  status: string | null;
}

/** Live queue updates over SSE.
 *
 *  The event carries no incident data worth rendering — it is a nudge, and the
 *  handler refetches. That is deliberate: pub/sub drops messages for anyone not
 *  currently subscribed, so treating the event as the source of truth would mean
 *  a dropped message becomes a missing row. Refetching means it costs one round
 *  trip instead.
 *
 *  `EventSource` cannot send an Authorization header, so the access token goes in
 *  the query string. It reconnects on its own, but not after a 401 — an expired
 *  token needs a new URL, so that case is handled here by refreshing and
 *  remounting the connection. */
export function useIncidentStream(enabled = true) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<StreamState>("connecting");
  const [lastEvent, setLastEvent] = useState<IncidentEvent | null>(null);
  // Bumped to force a reconnect with a fresh token after an auth failure.
  const [attempt, setAttempt] = useState(0);
  const retries = useRef(0);

  useEffect(() => {
    if (!enabled) {
      setState("offline");
      return;
    }

    const token = getAccessToken();
    if (!token) {
      setState("connecting");
      return;
    }

    const source = new EventSource(
      `${BASE}/incidents/stream?token=${encodeURIComponent(token)}`,
    );
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    source.onopen = () => {
      retries.current = 0;
      setState("live");
    };

    source.addEventListener("incident", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as IncidentEvent;
        setLastEvent(payload);
      } catch {
        /* a malformed event is not worth breaking the stream over */
      }
      // Invalidate rather than patch. The row the queue wants depends on the
      // filters in force, and the server is the only thing that knows them.
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    });

    source.onerror = () => {
      setState("offline");
      source.close();
      if (cancelled) return;

      // Back off rather than hammer: a console left open against a restarting
      // API should not turn into a reconnect storm.
      retries.current += 1;
      const delay = Math.min(1000 * 2 ** (retries.current - 1), 30_000);
      timer = setTimeout(() => {
        void refreshAccessToken().finally(() => {
          if (!cancelled) setAttempt((n) => n + 1);
        });
      }, delay);
    };

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      source.close();
    };
  }, [enabled, queryClient, attempt]);

  return { state, lastEvent };
}
