import type { TokenPair } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";
const REFRESH_KEY = "awdsoc.refresh";

/** The access token lives in memory only. The refresh token is the one thing
 *  that survives a reload. */
let accessToken: string | null = null;
let onSignedOut: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

/** For `EventSource`, which cannot send an Authorization header and so needs the
 *  token in the URL. Nothing else should read this. */
export function getAccessToken(): string | null {
  return accessToken;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setRefreshToken(token: string | null) {
  if (token) localStorage.setItem(REFRESH_KEY, token);
  else localStorage.removeItem(REFRESH_KEY);
}

export function storeTokens(pair: TokenPair) {
  setAccessToken(pair.access_token);
  setRefreshToken(pair.refresh_token);
}

export function clearTokens() {
  setAccessToken(null);
  setRefreshToken(null);
}

export function onSessionEnded(handler: () => void) {
  onSignedOut = handler;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg;
  } catch {
    /* fall through to the status text */
  }
  return response.statusText || "Request failed";
}

let refreshInFlight: Promise<boolean> | null = null;

/** One refresh at a time: a page of parallel queries hitting a stale token must
 *  not spend the single-use refresh token several times over. */
async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const refresh = getRefreshToken();
      if (!refresh) return false;
      const response = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!response.ok) {
        clearTokens();
        return false;
      }
      storeTokens((await response.json()) as TokenPair);
      return true;
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Internal: stops a refresh loop. */
  retry?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, retry = true } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && retry && getRefreshToken()) {
    if (await refreshAccessToken()) {
      return api<T>(path, { ...options, retry: false });
    }
    onSignedOut?.();
    throw new ApiError(401, "Your session has ended. Sign in again.");
  }

  if (!response.ok) throw new ApiError(response.status, await readError(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export { refreshAccessToken };

/** Health sits outside the versioned API, at `/api/healthz`. Traefik routes
 *  `/api` to the backend, so the bare `/healthz` the container probe uses is not
 *  reachable from a browser. */
export async function rootGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok && response.status !== 503) {
    throw new ApiError(response.status, await readError(response));
  }
  return (await response.json()) as T;
}
