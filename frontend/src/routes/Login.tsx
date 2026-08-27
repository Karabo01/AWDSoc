import { type FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";

export function Login() {
  const { signIn, status } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "authenticated") return <Navigate to="/" replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not reach the console. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-lg border border-line bg-ink-800 p-8"
      >
        <h1 className="text-lg font-semibold">AWDTECH SOC Console</h1>
        <p className="mt-1 text-sm text-dim">Sign in to continue.</p>

        <label className="mt-6 block text-sm text-dim" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 w-full rounded border border-line bg-ink-900 px-3 py-2 text-sm outline-none transition focus:border-accent"
        />

        <label className="mt-4 block text-sm text-dim" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded border border-line bg-ink-900 px-3 py-2 text-sm outline-none transition focus:border-accent"
        />

        {error && (
          <p role="alert" className="mt-4 text-sm text-[color:var(--sev-crit)]">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="mt-6 w-full rounded bg-accent px-3 py-2 text-sm font-medium text-ink-900 transition hover:brightness-110 disabled:opacity-60"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
