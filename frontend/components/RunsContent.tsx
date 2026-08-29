"use client";

import { useEffect, useState } from "react";

import { StatusPill } from "./Badges";
import Icon from "./Icon";
import { SkeletonRow } from "./Skeleton";
import { API, useDashboard } from "../lib/dashboard-context";

type Run = {
  run_id: string; triggered_by: string; started_at: string; completed_at: string | null;
  status: string; total: number; passed: number; failed: number; errored: number;
  manual_review: number; compliance_pct: number | null;
};

function duration(started: string, completed: string | null): string {
  if (!completed) return "—";
  const s = (new Date(completed).getTime() - new Date(started).getTime()) / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function statusTone(status: string): "success" | "error" | "warning" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  return "warning";
}

export default function RunsContent() {
  const { scanProgress } = useDashboard();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [total, setTotal] = useState(0);
  const [rowCap, setRowCap] = useState(100);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const r = await fetch(`${API}/api/runs`, { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setRuns(body.runs);
      setTotal(body.total);
      setRowCap(body.row_cap);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  // Reload whenever a scan this session triggered finishes, so a freshly-completed
  // run appears without a manual refresh.
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [scanProgress?.status]);
  useEffect(() => { load(); }, []);

  if (error) {
    return (
      <div className="flex flex-col items-center gap-sm rounded-lg border border-error-container bg-error-container p-lg text-center">
        <Icon name="error" className="text-[28px] text-on-error-container" />
        <p className="font-body-md text-body-md text-on-error-container">Couldn&apos;t load runs: {error}</p>
        <button onClick={load} className="rounded bg-on-error-container px-md py-sm font-body-sm text-body-sm font-semibold text-error-container hover:opacity-90">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-sm">
      {total > rowCap && (
        <p className="font-body-sm text-body-sm text-on-surface-variant">
          Showing the {rowCap} most recent of {total} runs.
        </p>
      )}
      <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-outline-variant bg-surface-container-low">
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Run</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Status</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Initiated by</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Started</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Duration</th>
                <th className="p-sm text-right font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Pass / Fail</th>
                <th className="p-sm text-right font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Compliance</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant"></th>
              </tr>
            </thead>
            <tbody className="font-body-md text-body-md text-on-surface">
              {!runs && Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} cols={8} />)}
              {runs?.map((r) => (
                <tr key={r.run_id} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low">
                  <td className="p-sm font-data-mono text-data-mono">{r.run_id.slice(0, 8)}</td>
                  <td className="p-sm">
                    <StatusPill tone={statusTone(r.status)} pulse={r.status === "running"}>{r.status}</StatusPill>
                  </td>
                  {/* NEVER "Scheduled System Task" -- there is no scheduler. This is
                      always the real session identity that hit POST /api/scans, or
                      a fixture label from a documented test/scale run. */}
                  <td className="p-sm">{r.triggered_by}</td>
                  <td className="p-sm font-body-sm text-body-sm text-on-surface-variant">
                    {new Date(r.started_at).toLocaleString()}
                  </td>
                  <td className="p-sm font-data-mono text-data-mono">{duration(r.started_at, r.completed_at)}</td>
                  <td className="p-sm text-right font-data-mono text-data-mono">
                    <span className="text-success">{r.passed}</span> / <span className="text-error">{r.failed}</span>
                  </td>
                  <td className="p-sm text-right font-data-mono text-data-mono">
                    {r.compliance_pct != null ? `${r.compliance_pct}%` : "—"}
                  </td>
                  <td className="p-sm text-right">
                    {r.status === "completed" && (
                      <a
                        href={`/findings?run=${r.run_id}`}
                        className="rounded px-sm py-1 font-body-sm text-body-sm text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
                      >
                        View findings
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
