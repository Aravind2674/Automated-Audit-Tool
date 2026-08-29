"use client";

import Image from "next/image";
import { useState } from "react";

import { API } from "../lib/dashboard-context";

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
    <main className="flex min-h-screen items-center justify-center bg-surface p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-md rounded-lg border border-outline-variant bg-surface-container-lowest p-lg"
      >
        <div className="flex items-center gap-sm">
          <Image src="/audittool_logo.png" alt="AuditTool" width={36} height={36} className="rounded" />
          <div>
            <h1 className="font-headline-sm text-headline-sm font-bold text-primary">AuditTool</h1>
            <p className="font-body-sm text-body-sm text-on-surface-variant">Sign in to continue</p>
          </div>
        </div>

        <label className="block">
          <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Username</span>
          <input
            value={username} onChange={(e) => setUsername(e.target.value)}
            autoComplete="username" required
            className="mt-1 w-full rounded border border-outline-variant bg-surface px-sm py-sm font-body-md text-body-md text-on-surface focus:border-primary focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Password</span>
          <input
            type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password" required
            className="mt-1 w-full rounded border border-outline-variant bg-surface px-sm py-sm font-body-md text-body-md text-on-surface focus:border-primary focus:outline-none"
          />
        </label>

        {error && (
          <p className="rounded border border-error-container bg-error-container px-sm py-sm font-body-sm text-body-sm text-on-error-container">
            {error}
          </p>
        )}

        <button
          type="submit" disabled={busy}
          className="w-full rounded bg-primary px-md py-sm font-body-md text-body-md font-semibold text-on-primary transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
