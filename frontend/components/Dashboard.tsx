"use client";

import { useEffect, useState } from "react";

import Login from "./Login";

/**
 * Every figure rendered here comes straight from /api/dashboard, which derives it
 * from the append-only `results` table. Nothing is recomputed client-side -- if the
 * browser did its own arithmetic, the number on screen could disagree with the
 * database and there would be no way to tell which was right.
 *
 * tests/verify_phase6.py cross-checks each of these values against a direct SQL
 * query rather than against the API's own response.
 */

const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

type Summary = {
  total: number; passed: number; failed: number; errored: number;
  manual_review: number; open_findings: number; accepted_risk: number;
  compliance_pct: number | null;
};
type Domain = {
  category: string; total: number; passed: number; failed: number;
  errored: number; open_findings: number; compliance_pct: number | null;
};
type Exc = {
  exception_id: string; control_id: string; severity: string; title: string;
  status: string; requested_by: string; approved_by: string | null;
  expiry_date: string; expired: boolean; days_until_expiry: number | null;
  justification: string;
};
type TrendRow = {
  run_id: string; completed_at: string; passed: number; failed: number;
  errored: number; compliance_pct: number | null;
};
type DriftRow = {
  kind: string; control_id: string; severity: string;
  previous_outcome: string | null; current_outcome: string | null;
};
type Payload = {
  run_id: string; generated_at: string; summary: Summary;
  per_domain: Domain[]; open_findings_by_severity: Record<string, number>;
  exceptions: Exc[]; trend: TrendRow[]; drift_since_previous_run: DriftRow[];
  drift_counts: Record<string, number>; drift_total: number; drift_row_cap: number;
  active_runs: { run_id: string; triggered_by: string; started_at: string; status: string }[];
  viewer: string;
};

const SEV_COLOR: Record<string, string> = {
  critical: "bg-red-700", high: "bg-orange-600",
  medium: "bg-yellow-600", low: "bg-slate-500",
};

function Card({ label, value, sub, tone = "slate" }: {
  label: string; value: React.ReactNode; sub?: string; tone?: string;
}) {
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-semibold text-${tone}-800`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

/** Compliance % per run. Plain SVG -- no chart library, nothing to keep patched. */
function DriftChart({ trend }: { trend: TrendRow[] }) {
  if (trend.length === 0) return <p className="text-sm text-slate-500">No runs yet.</p>;

  const W = 720, H = 200, PAD = 34;
  const pts = trend.map((t, i) => {
    const x = PAD + (i * (W - 2 * PAD)) / Math.max(trend.length - 1, 1);
    const pct = t.compliance_pct ?? 0;
    const y = H - PAD - ((H - 2 * PAD) * pct) / 100;
    return { x, y, pct, t };
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
         aria-label="Compliance percentage per run over time">
      {[0, 25, 50, 75, 100].map((g) => {
        const y = H - PAD - ((H - 2 * PAD) * g) / 100;
        return (
          <g key={g}>
            <line x1={PAD} y1={y} x2={W - PAD} y2={y} stroke="#e2e8f0" strokeWidth="1" />
            <text x={4} y={y + 4} fontSize="10" fill="#64748b">{g}%</text>
          </g>
        );
      })}
      <polyline fill="none" stroke="#0f766e" strokeWidth="2"
                points={pts.map((p) => `${p.x},${p.y}`).join(" ")} />
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r="4" fill="#0f766e" />
          <text x={p.x} y={p.y - 10} fontSize="10" textAnchor="middle" fill="#0f766e">
            {p.pct}%
          </text>
          <text x={p.x} y={H - PAD + 14} fontSize="9" textAnchor="middle" fill="#64748b">
            {String(p.t.run_id).slice(0, 8)}
          </text>
        </g>
      ))}
    </svg>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    // credentials:"include" sends the HttpOnly session cookie. Without it the API
    // correctly returns 401 -- the cookie is not attached to cross-origin requests
    // by default, which is also what makes SameSite meaningful.
    fetch(`${API}/api/dashboard`, { credentials: "include" })
      .then((r) => {
        if (r.status === 401) {
          setNeedsLogin(true);
          return null;
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => { if (d) { setData(d); setNeedsLogin(false); } })
      .catch((e) => setError(String(e)));
  }, [reloadKey]);

  // While any scan is in flight, refresh until it finishes.
  //
  // POST /api/scans returns 202 immediately and the work continues in the
  // background, so a single refetch on trigger would show stale data and a dashboard
  // that looks idle while a scan is running -- the "silently block or hang"
  // appearance the async change exists to avoid. This is the same refresh path the
  // button already used, just repeated until active_runs empties.
  useEffect(() => {
    if (!data?.active_runs?.length) return;
    const id = setInterval(() => setReloadKey((k) => k + 1), 4000);
    return () => clearInterval(id);
  }, [data?.active_runs?.length]);

  // FR5: "the same audit can be re-executed on demand" -- a user-facing action, not
  // a developer running a Python file. Hits the authenticated POST /api/scans and
  // reloads so the new run_id becomes the dashboard's latest completed run.
  const [scanning, setScanning] = useState(false);
  const [scanMsg, setScanMsg] = useState<string | null>(null);

  async function runScan(mode: "cached" | "live") {
    setScanning(true);
    setScanMsg(null);
    try {
      const r = await fetch(`${API}/api/scans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ mode }),
      });
      if (r.status === 401) { setNeedsLogin(true); return; }
      const body = await r.json();
      if (!r.ok) { setScanMsg(`Scan failed: ${body.detail ?? r.status}`); return; }
      // 202 Accepted: the scan has STARTED, not finished. Saying otherwise would be
      // a lie the user could check.
      setScanMsg(
        `Scan ${String(body.run_id).slice(0, 8)} started (${body.targets ?? 1} target${(body.targets ?? 1) > 1 ? "s" : ""}) — running in the background.`
      );
      setReloadKey((k) => k + 1);
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

  if (needsLogin) return <Login onSuccess={() => { setNeedsLogin(false); setReloadKey((k) => k + 1); }} />;
  if (error) return <main className="p-8"><p className="text-red-700">Failed to load: {error}</p></main>;
  if (!data) return <main className="p-8"><p className="text-slate-500">Loading…</p></main>;

  const s = data.summary;
  const hasAws = data.per_domain.length > 0;

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Compliance Dashboard</h1>
          <p className="text-xs text-slate-500">
            Run <span className="font-mono">{data.run_id}</span> · latest completed scan
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">
            signed in as <span className="font-medium">{data.viewer}</span>
          </span>
          <button onClick={() => runScan("live")} disabled={scanning}
                  className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-600 disabled:opacity-50">
            {scanning ? "Scanning…" : "Run New Scan"}
          </button>
          <a href={`${API}/api/reports/pdf`}
             className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
            Export PDF report
          </a>
          <button onClick={logout}
                  className="rounded-md px-3 py-2 text-sm text-slate-600 ring-1 ring-slate-300 hover:bg-slate-50">
            Sign out
          </button>
        </div>
      </header>

      {data.active_runs?.length > 0 && (
        <div className="flex items-center gap-3 rounded-md bg-blue-50 p-3 text-sm text-blue-900 ring-1 ring-blue-200">
          <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-blue-600" />
          <span>
            <b>{data.active_runs.length} scan{data.active_runs.length > 1 ? "s" : ""} running.</b>{" "}
            {data.active_runs.map((r) => `${r.run_id.slice(0, 8)} (by ${r.triggered_by})`).join(", ")}
            {" — "}figures below are from the last completed run and will update automatically.
          </span>
        </div>
      )}

      {scanMsg && (
        <p className="rounded-md bg-teal-50 p-3 text-sm text-teal-900 ring-1 ring-teal-200">
          {scanMsg}
        </p>
      )}

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card label="Overall compliance" value={`${s.compliance_pct ?? "n/a"}%`}
              sub={`${s.passed} passed of ${s.passed + s.failed} scored`} tone="teal" />
        <Card label="Open findings" value={s.open_findings}
              sub={`${s.failed} failing, ${s.accepted_risk} accepted risk`} tone="red" />
        <Card label="Accepted risk" value={s.accepted_risk} sub="approved, unexpired" tone="amber" />
        <Card label="Not scored" value={s.errored + s.manual_review}
              sub={`${s.errored} error, ${s.manual_review} manual review`} tone="slate" />
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
          Open findings by severity
        </h2>
        <div className="flex flex-wrap gap-3">
          {["critical", "high", "medium", "low"].map((sev) => (
            <div key={sev} className="flex items-center gap-2">
              <span className={`inline-block h-3 w-3 rounded-full ${SEV_COLOR[sev]}`} />
              <span className="text-sm capitalize text-slate-700">{sev}</span>
              <span className="text-sm font-semibold">
                {data.open_findings_by_severity[sev] ?? 0}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
          Compliance by domain
        </h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase text-slate-500">
              <th className="py-2">Domain</th><th>Total</th><th>Pass</th><th>Fail</th>
              <th>Error</th><th>Open</th><th className="w-48">Compliance</th>
            </tr>
          </thead>
          <tbody>
            {data.per_domain.map((d) => (
              <tr key={d.category} className="border-b border-slate-100">
                <td className="py-2 font-medium">{d.category}</td>
                <td>{d.total}</td><td>{d.passed}</td><td>{d.failed}</td>
                <td>{d.errored}</td><td>{d.open_findings}</td>
                <td>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-28 rounded bg-slate-200">
                      <div className="h-2 rounded bg-teal-600"
                           style={{ width: `${d.compliance_pct ?? 0}%` }} />
                    </div>
                    <span className="tabular-nums">{d.compliance_pct ?? "n/a"}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
          Compliance trend
        </h2>
        <DriftChart trend={data.trend} />
        {data.drift_since_previous_run.length > 0 ? (
          <div className="mt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">
              Drift since previous run
              {data.drift_total > data.drift_since_previous_run.length && (
                <span className="ml-2 font-normal normal-case text-slate-400">
                  {data.drift_total} changes (
                  {Object.entries(data.drift_counts).map(([k, v]) => `${v} ${k}`).join(", ")}
                  ) — showing first {data.drift_row_cap} per category
                </span>
              )}
            </h3>
            <ul className="space-y-1 text-sm">
              {data.drift_since_previous_run.map((d, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                    d.kind === "improved" ? "bg-green-100 text-green-800"
                    : d.kind === "regressed" ? "bg-red-100 text-red-800"
                    : "bg-slate-100 text-slate-700"}`}>
                    {d.kind}
                  </span>
                  <span className="font-mono text-xs">{d.control_id}</span>
                  <span className="text-xs text-slate-500">
                    [{d.severity}] {d.previous_outcome ?? "—"} → {d.current_outcome ?? "—"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-500">No drift since the previous run.</p>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
          Exceptions
        </h2>
        {data.exceptions.length === 0 ? (
          <p className="text-sm text-slate-500">No approved exceptions.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase text-slate-500">
                <th className="py-2">Control</th><th>Severity</th><th>Requested</th>
                <th>Approved</th><th>Expiry</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.exceptions.map((e) => (
                <tr key={e.exception_id} className="border-b border-slate-100">
                  <td className="py-2 font-mono text-xs">{e.control_id}</td>
                  <td className="capitalize">{e.severity}</td>
                  <td>{e.requested_by}</td>
                  <td>{e.approved_by ?? "—"}</td>
                  <td className="tabular-nums text-xs">{e.expiry_date.slice(0, 19)}</td>
                  <td>
                    {e.expired ? (
                      <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                        expired — finding reopened
                      </span>
                    ) : (
                      <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                        active · {e.days_until_expiry}d left
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-3 text-xs text-slate-500">
          An exception suppresses a finding in the open-findings view but never rewrites
          the stored result, which remains <span className="font-semibold">fail</span>.
          Exceptions expire automatically — no permanent exceptions exist.
        </p>
      </section>

      {hasAws && (
        <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-900 ring-1 ring-amber-200">
          ⚠ AWS findings, where present, are verified against the <em>moto</em> mock
          library rather than a real AWS account and are not evidenced to the standard
          of the Linux findings. See architecture.md §3.6.
        </p>
      )}
    </main>
  );
}
