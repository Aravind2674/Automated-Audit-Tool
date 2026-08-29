"use client";

import { useState } from "react";

import AnimatedNumber from "./AnimatedNumber";
import { SeverityDot } from "./Badges";
import Icon from "./Icon";
import LiveIndicator from "./LiveIndicator";
import { OverviewSkeleton } from "./Skeleton";
import { useDashboard, type Domain } from "../lib/dashboard-context";

/** Compliance trend sparkline. Same simple path-and-area treatment as the mockup,
 * redrawn against real `trend` data instead of a fixed placeholder path. */
function TrendSparkline({ trend }: { trend: { compliance_pct: number | null }[] }) {
  if (trend.length === 0) {
    return <p className="font-body-sm text-body-sm text-on-surface-variant">No runs yet.</p>;
  }
  const W = 100, H = 100;
  const pts = trend.map((t, i) => {
    const x = trend.length === 1 ? 0 : (i * W) / (trend.length - 1);
    const y = H - (H * (t.compliance_pct ?? 0)) / 100;
    return `${x},${y}`;
  });
  const line = pts.join(" ");
  const area = `0,${H} ${line} ${W},${H}`;

  return (
    <div className="relative h-24 w-full overflow-hidden rounded bg-surface-container">
      <svg className="absolute bottom-0 h-full w-full" preserveAspectRatio="none" viewBox={`0 0 ${W} ${H}`}>
        <polygon points={area} fill="#dae2fd" opacity="0.4" />
        <polyline points={line} fill="none" stroke="#131b2e" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

function DomainRow({ d }: { d: Domain }) {
  const scored = d.passed + d.failed;
  const passPct = scored ? (d.passed / scored) * 100 : 0;
  const failPct = scored ? (d.failed / scored) * 100 : 0;
  return (
    <tr className="group border-b border-outline-variant last:border-0 hover:bg-surface-container-low">
      <td className="p-sm font-medium capitalize">{d.category.replace(/_/g, " ")}</td>
      <td className="p-sm text-right font-data-mono text-data-mono">
        <AnimatedNumber value={d.total} />
      </td>
      <td className="p-sm text-right font-data-mono text-data-mono">
        <AnimatedNumber value={d.passed} />
      </td>
      <td className="p-sm text-right font-data-mono text-data-mono">
        <AnimatedNumber value={d.failed} />
      </td>
      <td className="p-sm">
        <div className="flex h-2 w-full overflow-hidden rounded bg-surface-container">
          <div className="h-full bg-primary-container transition-[width] duration-700 ease-out" style={{ width: `${passPct}%` }} />
          <div className="h-full bg-error transition-[width] duration-700 ease-out" style={{ width: `${failPct}%` }} />
        </div>
      </td>
    </tr>
  );
}

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

const HOW_IT_WORKS = [
  { title: "Collect", body: "SSH into Linux hosts and read the AWS API for the resources in scope — read-only, nothing is changed on the systems being audited." },
  { title: "Evaluate", body: "Every collected value is checked against the YAML control library — 18 CIS Linux controls, 6 AWS controls — and recorded pass, fail, error, or manual review." },
  { title: "Report", body: "Results, exceptions and the full audit trail are stored append-only in PostgreSQL and surfaced here and in the framework-mapped PDF export." },
];

export default function OverviewContent() {
  const { data, scanMsg, scanProgress } = useDashboard();
  const [howOpen, setHowOpen] = useState(true);
  if (!data) return <OverviewSkeleton />;

  const s = data.summary;
  const scored = s.passed + s.failed;

  return (
    <div className="flex flex-col gap-margin">
      <div className="flex items-center justify-between">
        <LiveIndicator generatedAt={data.generated_at} live={data.active_runs.length > 0 || !!scanProgress} />
      </div>

      {data.active_runs.length > 0 && (
        <div className="flex items-center gap-sm rounded border border-outline-variant bg-surface-container-lowest px-md py-sm font-body-sm text-body-sm text-on-surface-variant">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-primary" />
          <span>
            <b className="text-on-surface">
              {data.active_runs.length} scan{data.active_runs.length > 1 ? "s" : ""} running
            </b>{" "}
            — {data.active_runs.map((r) => `${r.run_id.slice(0, 8)} (${r.triggered_by})`).join(", ")}.
            Figures below are from the last completed run.
          </span>
        </div>
      )}
      {scanMsg && (
        <div className="rounded border border-outline-variant bg-surface-container-lowest px-md py-sm font-body-sm text-body-sm text-on-surface-variant">
          {scanMsg}
        </div>
      )}

      {/* Hero / high-level stats */}
      <div className="grid grid-cols-1 gap-md lg:grid-cols-3">
        <div className="flex flex-col items-center justify-center rounded-lg border border-outline-variant bg-surface-container-lowest p-lg text-center lg:col-span-1">
          <h2 className="mb-sm font-label-caps text-label-caps uppercase text-on-surface-variant">
            Overall Compliance
          </h2>
          <div className="mb-sm font-display-lg text-[64px] font-bold leading-none text-primary">
            <AnimatedNumber value={s.compliance_pct} decimals={s.compliance_pct != null && !Number.isInteger(s.compliance_pct) ? 1 : 0} suffix="%" />
          </div>
          <p className="font-body-md text-body-md text-on-surface-variant">
            <AnimatedNumber value={s.passed} /> of <AnimatedNumber value={scored} /> scored controls are currently passing.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-md md:grid-cols-3 lg:col-span-2">
          <div className="flex flex-col justify-between rounded-lg border border-outline-variant bg-surface-container-lowest p-md transition-shadow hover:shadow-sm">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Open Findings</span>
            <div className="mt-sm font-display-lg text-display-lg text-primary"><AnimatedNumber value={s.open_findings} /></div>
          </div>
          <div className="flex flex-col justify-between rounded-lg border border-outline-variant bg-surface-container-lowest p-md transition-shadow hover:shadow-sm">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Accepted Risk</span>
            <div className="mt-sm font-display-lg text-display-lg text-primary"><AnimatedNumber value={s.accepted_risk} /></div>
          </div>
          <div className="flex flex-col justify-between rounded-lg border border-outline-variant bg-surface-container-lowest p-md transition-shadow hover:shadow-sm">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Total Results</span>
            <div className="mt-sm font-display-lg text-display-lg text-primary"><AnimatedNumber value={s.total} /></div>
          </div>

          <div className="rounded-lg border border-outline-variant bg-surface-container-lowest p-md md:col-span-3">
            <div className="mb-sm flex items-center justify-between">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">
                Compliance Trend ({data.trend.length} run{data.trend.length === 1 ? "" : "s"})
              </span>
            </div>
            <TrendSparkline trend={data.trend} />
          </div>
        </div>
      </div>

      {/* Severity breakdown */}
      <section className="rounded-lg border border-outline-variant bg-surface-container-lowest p-md">
        <h3 className="mb-md font-headline-sm text-headline-sm text-primary">Open Findings by Severity</h3>
        <div className="grid grid-cols-2 gap-sm md:grid-cols-4">
          {SEVERITIES.map((sev) => (
            <div key={sev} className="flex flex-col rounded border border-outline-variant p-sm transition-colors hover:bg-surface-container-low">
              <div className="mb-xs flex items-center gap-xs">
                <SeverityDot severity={sev} />
                <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">{sev}</span>
              </div>
              <span className="font-display-md text-display-md">
                <AnimatedNumber value={data.open_findings_by_severity[sev] ?? 0} />
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Compliance by domain */}
      <section className="flex flex-col overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
        <div className="border-b border-outline-variant bg-surface-container p-md">
          <h3 className="font-headline-sm text-headline-sm text-primary">Compliance by Domain</h3>
        </div>
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-outline-variant bg-surface-container-low">
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Domain</th>
                <th className="w-20 p-sm text-right font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Total</th>
                <th className="w-20 p-sm text-right font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Pass</th>
                <th className="w-20 p-sm text-right font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Fail</th>
                <th className="w-64 p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Progress</th>
              </tr>
            </thead>
            <tbody className="font-body-md text-body-md text-on-surface">
              {data.per_domain.map((d) => <DomainRow key={d.category} d={d} />)}
            </tbody>
          </table>
        </div>
      </section>

      {/* How it works */}
      <div className="rounded-lg border border-outline-variant bg-surface-container-lowest">
        <button
          onClick={() => setHowOpen((v) => !v)}
          className="flex w-full items-center justify-between border-b border-outline-variant bg-surface-container-low p-md text-left"
        >
          <span className="font-headline-sm text-headline-sm text-primary">How it works</span>
          <Icon name="expand_more" className={`transition-transform ${howOpen ? "rotate-180" : ""}`} />
        </button>
        {howOpen && (
          <div className="flex flex-col gap-md p-md font-body-md text-body-md text-on-surface-variant md:flex-row">
            {HOW_IT_WORKS.map((step, i) => (
              <div key={step.title} className="flex flex-1 flex-col gap-xs rounded border border-outline-variant bg-surface p-sm">
                <div className="mb-xs flex h-8 w-8 items-center justify-center rounded-full bg-primary-container font-bold text-on-primary-container">
                  {i + 1}
                </div>
                <h4 className="font-semibold text-on-surface">{step.title}</h4>
                <p className="font-body-sm text-body-sm">{step.body}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
