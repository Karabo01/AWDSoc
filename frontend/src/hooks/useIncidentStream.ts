import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

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
 *  **Nothing is merged into the list automatically.** New incidents accumulate
 *  into a count the queue shows as a pill, and the analyst clicks to take them.
 *  A list that reorders itself under a pointer that is already moving toward a
 *  row is how the wrong case gets opened — per DESIGN §8.
 *
 *  The event itself carries no data worth rendering; it is a nudge, and merging
 *  refetches. That is deliberate: pub/sub drops messages for anyone not
 *  currently subscribed, so treating the event as the source of truth would turn
 *  a dropped message into a permanently missing row.
 *
 *  `EventSource` cannot send an Authorization header, so the access token goes
 *  in the query string. It reconnects on its own, but not after a 401 — an
 *  expired token needs a new URL, so that case is handled here. */
export function useIncidentStream(enabled = true) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<StreamState>("connecting");
  const [pending, setPending] = useState(0);
  // Bumped to force a reconnect with a fresh token after an auth failure.
  const [attempt, setAttempt] = useState(0);
  const retries = useRef(0);

  const merge = useCallback(() => {
    setPending(0);
    void queryClient.invalidateQueries({ queryKey: ["incidents"] });
  }, [queryClient]);

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
      let payload: IncidentEvent | null = null;
      try {
        payload = JSON.parse((event as MessageEvent).data) as IncidentEvent;
      } catch {
        return; // a malformed event is not worth breaking the stream over
      }

      // The overview is a set of counters nobody is pointing at, so it can
      // refresh itself. The queue cannot.
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      void queryClient.invalidateQueries({ queryKey: ["overview-trend"] });

      if (payload.kind === "created") {
        setPending((count) => count + 1);
      }
      // "updated" and "alert" touch a row that is already on screen. Refreshing
      // the detail behind the pane is safe; the list order is not disturbed.
      void queryClient.invalidateQueries({ queryKey: ["incident"] });
    });

    source.onerror = () => {
      setState("offline");
      source.close();
      if (cancelled) return;

      // Back off rather than hammer: a console left open against a restarting
      // API should not become a reconnect storm.
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

  return { state, pending, merge };
}
