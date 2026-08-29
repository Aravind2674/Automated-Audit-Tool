"use client";

import { useState } from "react";

import { OutcomeIndicator, SeverityBadge } from "./Badges";
import Icon from "./Icon";
import { OverviewSkeleton } from "./Skeleton";
import { useDashboard, type TrendRow } from "../lib/dashboard-context";

const DRIFT_META: Record<string, { label: string; icon: string; className: string }> = {
  improved: { label: "Improved", icon: "trending_up", className: "text-success" },
  regressed: { label: "Regressed", icon: "trending_down", className: "text-error" },
  appeared: { label: "New resource", icon: "add_circle", className: "text-on-surface-variant" },
  disappeared: { label: "Resource removed", icon: "remove_circle", className: "text-on-surface-variant" },
  other: { label: "Changed", icon: "sync_alt", className: "text-on-surface-variant" },
};

function TrendChart({ trend }: { trend: TrendRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (trend.length < 2) {
    return (
      <p className="font-body-sm text-body-sm text-on-surface-variant">
        Need at least two completed runs to plot a trend -- only {trend.length} so far.
      </p>
    );
  }
  const W = 600, H = 160, PAD = 24;
  const pts = trend.map((t, i) => {
    const x = PAD + (i * (W - PAD * 2)) / (trend.length - 1);
    const y = H - PAD - ((H - PAD * 2) * (t.compliance_pct ?? 0)) / 100;
    return { x, y, t };
  });
  const line = pts.map((p) => `${p.x},${p.y}`).join(" ");
  const area = `${PAD},${H - PAD} ${line} ${W - PAD},${H - PAD}`;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseLeave={() => setHover(null)}>
        {[0, 25, 50, 75, 100].map((g) => {
          const y = H - PAD - ((H - PAD * 2) * g) / 100;
          return <line key={g} x1={PAD} x2={W - PAD} y1={y} y2={y} stroke="currentColor" className="text-outline-variant" strokeWidth="1" />;
        })}
        <polygon points={area} fill="#dae2fd" opacity="0.4" />
        <polyline points={line} fill="none" stroke="#131b2e" strokeWidth="2" />
        {pts.map((p, i) => (
          <circle
            key={i} cx={p.x} cy={p.y} r={hover === i ? 5 : 3}
            fill={hover === i ? "#131b2e" : "#fff"} stroke="#131b2e" strokeWidth="1.5"
            className="cursor-pointer transition-all"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 -translate-y-full rounded border border-outline-variant bg-surface-container-lowest px-sm py-1 font-body-sm text-body-sm shadow-md"
          style={{ left: `${(pts[hover].x / W) * 100}%`, top: `${(pts[hover].y / H) * 100}%` }}
        >
          <div className="font-semibold text-on-surface">{pts[hover].t.compliance_pct ?? "—"}%</div>
          <div className="font-data-mono text-data-mono text-on-surface-variant">{pts[hover].t.run_id.slice(0, 8)}</div>
          <div className="text-on-surface-variant">{new Date(pts[hover].t.completed_at).toLocaleString()}</div>
        </div>
      )}
    </div>
  );
}

export default function HistoryContent() {
  const { data } = useDashboard();
  if (!data) return <OverviewSkeleton />;

  const buckets: Record<string, typeof data.drift_since_previous_run> = {};
  for (const row of data.drift_since_previous_run) {
    (buckets[row.kind] ??= []).push(row);
  }

  return (
    <div className="flex flex-col gap-margin">
      <section className="rounded-lg border border-outline-variant bg-surface-container-lowest p-md">
        <h3 className="mb-md font-headline-sm text-headline-sm text-primary">Compliance over time</h3>
        <TrendChart trend={data.trend} />
      </section>

      <section className="flex flex-col gap-md">
        <div className="flex items-center justify-between">
          <h3 className="font-headline-sm text-headline-sm text-primary">Drift since the previous run</h3>
          {data.drift_total > 0 && (
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              {data.drift_total} change{data.drift_total === 1 ? "" : "s"}
              {data.drift_total > data.drift_row_cap ? ` (showing ${data.drift_row_cap})` : ""}
            </span>
          )}
        </div>

        {data.trend.length < 2 ? (
          <p className="rounded-lg border border-outline-variant bg-surface-container-lowest p-md font-body-sm text-body-sm text-on-surface-variant">
            Drift needs two completed runs to compare -- run another scan to see what changed.
          </p>
        ) : data.drift_total === 0 ? (
          <div className="flex flex-col items-center gap-xs rounded-lg border border-outline-variant bg-surface-container-lowest p-lg text-center">
            <Icon name="check_circle" className="text-[28px] text-success" />
            <p className="font-body-md text-body-md text-on-surface">No drift -- identical posture to the previous run.</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-sm md:grid-cols-5">
              {Object.entries(data.drift_counts).map(([kind, count]) => {
                const meta = DRIFT_META[kind] ?? DRIFT_META.other;
                return (
                  <div key={kind} className="flex flex-col gap-1 rounded border border-outline-variant p-sm">
                    <div className={`flex items-center gap-xs ${meta.className}`}>
                      <Icon name={meta.icon} className="text-[18px]" />
                      <span className="font-label-caps text-label-caps uppercase">{meta.label}</span>
                    </div>
                    <span className="font-display-md text-display-md">{count}</span>
                  </div>
                );
              })}
            </div>

            <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-outline-variant bg-surface-container-low">
                    <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Change</th>
                    <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Severity</th>
                    <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Control</th>
                    <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Resource</th>
                    <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Was</th>
                    <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Now</th>
                  </tr>
                </thead>
                <tbody className="font-body-md text-body-md text-on-surface">
                  {data.drift_since_previous_run.map((d, i) => {
                    const meta = DRIFT_META[d.kind] ?? DRIFT_META.other;
                    return (
                      <tr key={i} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low">
                        <td className={`p-sm ${meta.className}`}>
                          <span className="inline-flex items-center gap-xs"><Icon name={meta.icon} className="text-[16px]" />{meta.label}</span>
                        </td>
                        <td className="p-sm"><SeverityBadge severity={d.severity} /></td>
                        <td className="p-sm font-data-mono text-data-mono">{d.control_id}</td>
                        <td className="p-sm font-data-mono text-data-mono">{d.resource_id}</td>
                        <td className="p-sm">{d.previous_outcome ? <OutcomeIndicator outcome={d.previous_outcome} /> : "—"}</td>
                        <td className="p-sm">{d.current_outcome ? <OutcomeIndicator outcome={d.current_outcome} /> : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
