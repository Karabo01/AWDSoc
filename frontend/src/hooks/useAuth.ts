import { create } from "zustand";

import {
  api,
  clearTokens,
  getRefreshToken,
  refreshAccessToken,
  storeTokens,
} from "@/api/client";
import type { CurrentUser, TokenPair } from "@/api/types";

interface AuthState {
  user: CurrentUser | null;
  /** null while we are still deciding whether a stored session is good. */
  status: "loading" | "authenticated" | "anonymous";
  error: string | null;
  restore: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  switchTenant: (tenantId: string | null) => Promise<void>;
}

async function loadMe(): Promise<CurrentUser> {
  return api<CurrentUser>("/auth/me");
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: "loading",
  error: null,

  restore: async () => {
    if (!getRefreshToken()) {
      set({ status: "anonymous", user: null });
      return;
    }
    if (!(await refreshAccessToken())) {
      set({ status: "anonymous", user: null });
      return;
    }
    try {
      set({ user: await loadMe(), status: "authenticated" });
    } catch {
      clearTokens();
      set({ status: "anonymous", user: null });
    }
  },

  signIn: async (email, password) => {
    set({ error: null });
    const pair = await api<TokenPair>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    storeTokens(pair);
    set({ user: await loadMe(), status: "authenticated" });
  },

  signOut: async () => {
    const refresh = getRefreshToken();
    if (refresh) {
      await api("/auth/logout", { method: "POST", body: { refresh_token: refresh } }).catch(
        () => undefined,
      );
    }
    clearTokens();
    set({ user: null, status: "anonymous", error: null });
  },

  switchTenant: async (tenantId) => {
    const pair = await api<TokenPair>("/auth/switch-tenant", {
      method: "POST",
      body: { tenant_id: tenantId },
    });
    storeTokens(pair);
    set({ user: await loadMe() });
  },
}));
