"use client";

import { useEffect, useState } from "react";

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

  useEffect(() => {
    fetch(`${API}/api/dashboard`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

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
        <a href={`${API}/api/reports/pdf`}
           className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
          Export PDF report
        </a>
      </header>

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
