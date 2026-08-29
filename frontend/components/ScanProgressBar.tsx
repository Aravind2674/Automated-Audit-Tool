"use client";

import type { ScanProgress } from "../lib/dashboard-context";
import Icon from "./Icon";

/**
 * Renders exactly what GET /api/scans/{run_id} reports -- nothing here is
 * simulated. Two real phases, because they ARE two different things happening on
 * the backend: collection is sequential SSH per target (network-bound, dominates
 * wall-clock time at scale -- 128s for 50 targets per Phase 8), evaluation is
 * in-process control logic against already-collected resources (CPU-bound, fast).
 * Showing one blended bar would hide that a scan can sit at "60%" for a long time
 * because it's still opening SSH connections, not stuck.
 */
export default function ScanProgressBar({ progress }: { progress: ScanProgress }) {
  const collectPct = progress.total_targets
    ? Math.min(100, (progress.targets_collected / progress.total_targets) * 100) : 0;
  const evalPct = progress.total_controls
    ? Math.min(100, (progress.controls_evaluated / progress.total_controls) * 100) : 0;

  const label =
    progress.phase === "collecting"
      ? `Collecting target ${progress.targets_collected} of ${progress.total_targets}`
      : progress.phase === "evaluating"
      ? `Evaluating control ${progress.controls_evaluated} of ${progress.total_controls}`
      : progress.phase === "failed"
      ? "Scan failed"
      : `Completed — ${progress.results} results`;

  return (
    <div className="flex items-center gap-md rounded border border-outline-variant bg-surface-container-lowest px-md py-sm">
      <Icon
        name={progress.phase === "done" ? "task_alt" : progress.phase === "failed" ? "error" : "sync"}
        className={`text-[20px] ${progress.phase === "collecting" || progress.phase === "evaluating" ? "animate-spin" : ""} ${
          progress.phase === "done" ? "text-success" : progress.phase === "failed" ? "text-error" : "text-primary"
        }`}
      />
      <div className="flex min-w-[220px] flex-1 flex-col gap-1">
        <div className="flex items-center justify-between font-body-sm text-body-sm">
          <span className="font-medium text-on-surface">{label}</span>
          <span className="font-data-mono text-data-mono text-on-surface-variant">
            {progress.run_id.slice(0, 8)}
          </span>
        </div>
        <div className="flex h-1.5 gap-1 overflow-hidden rounded-full bg-surface-container">
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
            style={{ width: `${progress.phase === "collecting" ? collectPct : 100}%` }}
          />
          <div
            className="h-full rounded-full bg-success transition-[width] duration-500 ease-out"
            style={{
              width: `${progress.phase === "evaluating" || progress.phase === "done" ? evalPct : 0}%`,
              opacity: progress.phase === "collecting" ? 0.25 : 1,
            }}
          />
        </div>
      </div>
    </div>
  );
}
