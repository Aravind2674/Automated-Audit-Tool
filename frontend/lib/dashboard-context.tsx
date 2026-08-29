"use client";

import { createContext, useContext, useEffect, useState } from "react";

/**
 * Single shared fetch of /api/dashboard, plus the scan-trigger action, provided to
 * every page through context. This exists so:
 *
 *   - Auth (the 401 check) happens once, at the shell, not independently on every
 *     page.
 *   - "Run Scan" and the active-scan indicator are the SAME control on every page
 *     (matching the mockups, where it appears identically across all five), backed
 *     by one poll loop rather than five independent ones.
 *   - Every number a page renders still comes from this one real payload -- nothing
 *     is computed or cached client-side outside of it.
 */

/**
 * The API base MUST track whatever hostname the frontend is actually being viewed
 * from ("localhost" vs "127.0.0.1" vs a LAN IP), not a hardcoded default. Those
 * hostnames all mean "this machine" to a person, but the browser treats them as
 * different *sites* for cookie purposes: a SameSite=Lax session cookie set by a
 * cross-site fetch() (e.g. page on localhost:3000 calling 127.0.0.1:8000) is never
 * sent back on the next cross-site fetch() -- only on a top-level navigation. That
 * silently breaks login: the POST to /api/auth/login succeeds and sets the cookie,
 * but the very next GET /api/dashboard doesn't carry it, comes back 401, and the
 * app (correctly, given what it can see) drops back to the login screen -- looking
 * exactly like the button did nothing. Matching the API host to window.location's
 * host keeps every request same-site regardless of which hostname was typed in.
 */
export const API =
  process.env.NEXT_PUBLIC_API_BASE ||
  (typeof window !== "undefined" ? `http://${window.location.hostname}:8000` : "http://127.0.0.1:8000");

type Summary = {
  total: number; passed: number; failed: number; errored: number;
  manual_review: number; open_findings: number; accepted_risk: number;
  compliance_pct: number | null;
};
export type Domain = {
  category: string; total: number; passed: number; failed: number;
  errored: number; open_findings: number; compliance_pct: number | null;
};
export type Exc = {
  exception_id: string; control_id: string; resource_id: string; severity: string;
  title: string; status: string; requested_by: string; approved_by: string | null;
  approval_date: string | null; expiry_date: string; expired: boolean;
  days_until_expiry: number | null; justification: string;
  compensating_control: string | null;
};
export type TrendRow = {
  run_id: string; completed_at: string; passed: number; failed: number;
  errored: number; compliance_pct: number | null;
};
export type DriftRow = {
  kind: string; control_id: string; resource_id: string; severity: string;
  previous_outcome: string | null; current_outcome: string | null;
};
export type ActiveRun = { run_id: string; triggered_by: string; started_at: string; status: string };
export type DashboardPayload = {
  run_id: string; generated_at: string; summary: Summary;
  per_domain: Domain[]; open_findings_by_severity: Record<string, number>;
  exceptions: Exc[]; trend: TrendRow[]; drift_since_previous_run: DriftRow[];
  drift_counts: Record<string, number>; drift_total: number; drift_row_cap: number;
  active_runs: ActiveRun[];
  viewer: string;
};

/**
 * Real progress from GET /api/scans/{run_id} -- every field here is backed by an
 * actual DB count (see backend/api/main.py::scan_status), not a client-side
 * simulation. `phase` is derived, not returned by the API: collection (SSH per
 * target) is the slow, network-bound half of a scan and finishes before a single
 * result row exists, so "evaluating" only starts once every target is collected.
 */
export type ScanProgress = {
  run_id: string;
  status: "running" | "completed" | "failed";
  phase: "collecting" | "evaluating" | "done" | "failed";
  targets_collected: number; total_targets: number;
  controls_evaluated: number; total_controls: number;
  results: number;
};

type Ctx = {
  data: DashboardPayload | null;
  error: string | null;
  needsLogin: boolean;
  reload: () => void;
  runScan: (mode: "cached" | "live", targets?: number) => Promise<void>;
  scanning: boolean;
  scanProgress: ScanProgress | null;
  scanMsg: string | null;
  logout: () => Promise<void>;
};

const DashboardContext = createContext<Ctx | null>(null);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [scanMsg, setScanMsg] = useState<string | null>(null);
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);

  useEffect(() => {
    // credentials:"include" sends the HttpOnly session cookie. Without it the API
    // correctly returns 401 -- the cookie is not attached to cross-origin requests
    // by default, which is also what makes SameSite meaningful.
    fetch(`${API}/api/dashboard`, { credentials: "include" })
      .then((r) => {
        if (r.status === 401) { setNeedsLogin(true); return null; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => { if (d) { setData(d); setNeedsLogin(false); setError(null); } })
      .catch((e) => setError(String(e)));
  }, [reloadKey]);

  // While any scan is in flight, refresh until it finishes. POST /api/scans returns
  // 202 immediately and the work continues in the background, so a single refetch
  // on trigger would show stale data everywhere -- the "silently block or hang"
  // appearance the async change was built to avoid.
  useEffect(() => {
    if (!data?.active_runs?.length) return;
    const id = setInterval(() => setReloadKey((k) => k + 1), 4000);
    return () => clearInterval(id);
  }, [data?.active_runs?.length]);

  // Fast per-run poll for a scan THIS session triggered. Separate from the 4s
  // active_runs poll above (which exists to notice scans triggered elsewhere) --
  // this one drives visible, moment-to-moment progress, so it polls much more
  // often (900ms) for the one run this tab actually cares about right now.
  async function pollRun(runId: string) {
    for (;;) {
      let body: any;
      try {
        const r = await fetch(`${API}/api/scans/${runId}`, { credentials: "include" });
        if (r.status === 401) { setNeedsLogin(true); return; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        body = await r.json();
      } catch (e) {
        setScanMsg(`Lost contact with scan ${runId.slice(0, 8)}: ${String(e)}`);
        break;
      }

      const collecting = body.targets_collected < body.total_targets;
      const phase: ScanProgress["phase"] =
        body.status === "failed" ? "failed"
        : body.status === "completed" ? "done"
        : collecting ? "collecting" : "evaluating";

      setScanProgress({
        run_id: body.run_id, status: body.status, phase,
        targets_collected: body.targets_collected, total_targets: body.total_targets,
        controls_evaluated: body.controls_evaluated, total_controls: body.total_controls,
        results: body.results,
      });

      if (body.status === "completed" || body.status === "failed") {
        if (body.status === "failed") setScanMsg(`Scan ${runId.slice(0, 8)} failed.`);
        setReloadKey((k) => k + 1); // pick up the finished run's real numbers
        // Leave the finished state visible for a moment rather than snapping the
        // progress UI away the instant the last request lands.
        await new Promise((res) => setTimeout(res, 1400));
        setScanProgress(null);
        break;
      }
      await new Promise((res) => setTimeout(res, 900));
    }
  }

  async function runScan(mode: "cached" | "live", targets = 1) {
    setScanning(true);
    setScanMsg(null);
    try {
      const r = await fetch(`${API}/api/scans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ mode, targets }),
      });
      if (r.status === 401) { setNeedsLogin(true); return; }
      const body = await r.json();
      if (!r.ok) { setScanMsg(`Scan failed: ${body.detail ?? r.status}`); return; }
      // 202 Accepted: the scan has STARTED, not finished. Saying otherwise would be
      // a lie the user could check.
      setScanProgress({
        run_id: body.run_id, status: "running", phase: "collecting",
        targets_collected: 0, total_targets: targets,
        controls_evaluated: 0, total_controls: 0, results: 0,
      });
      await pollRun(body.run_id);
    } catch (e) {
      setScanMsg(`Scan failed: ${String(e)}`);
    } finally {
      setScanning(false);
    }
  }

  async function logout() {
    await fetch(`${API}/api/auth/logout`, { method: "POST", credentials: "include" });
    setData(null);
    setNeedsLogin(true);
  }

  return (
    <DashboardContext.Provider
      value={{
        data, error, needsLogin,
        reload: () => setReloadKey((k) => k + 1),
        runScan, scanning, scanProgress, scanMsg, logout,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard(): Ctx {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard() must be used inside <DashboardProvider>");
  return ctx;
}
