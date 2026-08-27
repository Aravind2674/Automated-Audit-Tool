"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

/**
 * Session login. The session id never reaches this component: the API sets an
 * HttpOnly cookie, which JavaScript cannot read, so an XSS flaw in the dashboard
 * cannot exfiltrate the session. That is the entire reason for HttpOnly, and it is
 * why `credentials: "include"` is used rather than storing a token in localStorage.
 *
 * The error message is deliberately identical for "no such user" and "wrong
 * password" — distinguishing them turns the login form into a username enumerator.
 */
export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) {
        setError("Invalid username or password.");
        return;
      }
      onSuccess();
    } catch {
      setError("Could not reach the API. Is the backend running on port 8000?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={submit}
            className="w-full max-w-sm space-y-4 rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div>
          <h1 className="text-xl font-semibold">IT Systems Audit Tool</h1>
          <p className="mt-1 text-xs text-slate-500">Sign in to view compliance data.</p>
        </div>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Username
          </span>
          <input value={username} onChange={(e) => setUsername(e.target.value)}
                 autoComplete="username" required
                 className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                            focus:border-slate-500 focus:outline-none" />
        </label>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Password
          </span>
          <input type="password" value={password}
                 onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" required
                 className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                            focus:border-slate-500 focus:outline-none" />
        </label>

        {error && (
          <p className="rounded-md bg-red-50 p-2 text-xs text-red-800 ring-1 ring-red-200">
            {error}
          </p>
        )}

        <button type="submit" disabled={busy}
                className="w-full rounded-md bg-slate-800 px-4 py-2 text-sm font-medium
                           text-white hover:bg-slate-700 disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
