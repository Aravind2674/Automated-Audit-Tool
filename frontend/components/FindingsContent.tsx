"use client";

import { useSearchParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState } from "react";

import { OutcomeIndicator, SeverityBadge } from "./Badges";
import Icon from "./Icon";
import { SkeletonRow } from "./Skeleton";
import { API, useDashboard } from "../lib/dashboard-context";

type Finding = {
  result_id: string; control_id: string; resource_id: string; outcome: string;
  evidence: unknown; evaluated_at: string; title: string; severity: string;
  category: string; remediation: string; framework_mappings: Record<string, string>;
  suppressed: boolean; provider: string;
};

const FILTERS = ["open", "all"] as const;
type Filter = (typeof FILTERS)[number];

function keyOf(f: Finding) {
  return `${f.control_id}:${f.resource_id}`;
}

/** Inline request-exception form -- expands under the row it belongs to rather
 * than a modal, so the finding you're requesting an exception FOR stays visible
 * the whole time you're filling out why. */
function RequestExceptionForm({
  finding, onDone, onCancel,
}: { finding: Finding; onDone: () => void; onCancel: () => void }) {
  const [justification, setJustification] = useState("");
  const [expiryDate, setExpiryDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return d.toISOString().slice(0, 10);
  });
  const [compensating, setCompensating] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (justification.trim().length < 10) {
      setError("Justification needs at least 10 characters -- a real reviewer has to act on this.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/exceptions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          control_id: finding.control_id,
          resource_id: finding.resource_id,
          justification,
          expiry_date: new Date(`${expiryDate}T23:59:59Z`).toISOString(),
          compensating_control: compensating || undefined,
        }),
      });
      const body = await r.json();
      if (!r.ok) { setError(body.detail ?? `HTTP ${r.status}`); return; }
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className="bg-surface-container-low">
      <td colSpan={7} className="p-md">
        <div className="animate-[fadeIn_150ms_ease-out] flex flex-col gap-sm rounded border border-outline-variant bg-surface p-md">
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            Requesting an exception for <span className="font-data-mono text-data-mono text-on-surface">{finding.control_id}</span> on{" "}
            <span className="font-data-mono text-data-mono text-on-surface">{finding.resource_id}</span>. This goes to{" "}
            <span className="font-medium text-on-surface">pending_review</span> -- it does not suppress the finding until a
            different reviewer approves it.
          </p>
          <label className="flex flex-col gap-1">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Justification</span>
            <textarea
              value={justification} onChange={(e) => setJustification(e.target.value)}
              rows={2} placeholder="Why is this an acceptable risk right now?"
              className="rounded border border-outline-variant bg-surface px-sm py-sm font-body-sm text-body-sm text-on-surface focus:border-primary focus:outline-none"
            />
          </label>
          <div className="flex flex-wrap gap-md">
            <label className="flex flex-col gap-1">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Expires</span>
              <input
                type="date" value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)}
                className="rounded border border-outline-variant bg-surface px-sm py-sm font-body-sm text-body-sm text-on-surface focus:border-primary focus:outline-none"
              />
            </label>
            <label className="flex flex-1 min-w-[200px] flex-col gap-1">
              <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Compensating control (optional)</span>
              <input
                value={compensating} onChange={(e) => setCompensating(e.target.value)}
                className="rounded border border-outline-variant bg-surface px-sm py-sm font-body-sm text-body-sm text-on-surface focus:border-primary focus:outline-none"
              />
            </label>
          </div>
          {error && (
            <p className="rounded border border-error-container bg-error-container px-sm py-1 font-body-sm text-body-sm text-on-error-container">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-sm">
            <button onClick={onCancel} className="rounded px-md py-sm font-body-sm text-body-sm text-on-surface-variant hover:bg-surface-container-high">
              Cancel
            </button>
            <button
              onClick={submit} disabled={busy}
              className="rounded bg-primary px-md py-sm font-body-sm text-body-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Submitting…" : "Submit request"}
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}

export default function FindingsContent() {
  const { data: dash, reload } = useDashboard();
  const searchParams = useSearchParams();
  const pinnedRun = searchParams.get("run"); // set when arriving via Runs' "View findings"
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("open");
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const [requestingFor, setRequestingFor] = useState<string | null>(null);
  const [justRequested, setJustRequested] = useState<Set<string>>(new Set());

  async function load() {
    try {
      const qs = pinnedRun ? `?run_id=${pinnedRun}` : "";
      const r = await fetch(`${API}/api/findings${qs}`, { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setFindings(body.findings);
      setRunId(body.run_id);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  // Reload whenever the shared dashboard run_id changes (i.e. a scan just
  // completed) -- Findings shows the SAME run everything else does, never a
  // stale snapshot from before the last scan. Pinned to one run instead when
  // arriving via a Runs row's "View findings" link.
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [dash?.run_id, pinnedRun]);

  const visible = useMemo(() => {
    if (!findings) return [];
    if (filter === "all") return findings;
    return findings.filter((f) => f.outcome !== "pass" && !f.suppressed);
  }, [findings, filter]);

  if (error) {
    return (
      <div className="flex flex-col items-center gap-sm rounded-lg border border-error-container bg-error-container p-lg text-center">
        <Icon name="error" className="text-[28px] text-on-error-container" />
        <p className="font-body-md text-body-md text-on-error-container">Couldn&apos;t load findings: {error}</p>
        <button onClick={load} className="rounded bg-on-error-container px-md py-sm font-body-sm text-body-sm font-semibold text-error-container hover:opacity-90">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-md">
      {pinnedRun && (
        <div className="flex items-center justify-between rounded border border-outline-variant bg-surface-container-lowest px-md py-sm font-body-sm text-body-sm">
          <span>
            Showing findings for run <span className="font-data-mono text-data-mono">{runId?.slice(0, 8) ?? pinnedRun.slice(0, 8)}</span>, not the latest.
          </span>
          <a href="/findings" className="rounded px-sm py-1 text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface">
            Back to latest
          </a>
        </div>
      )}
      <div className="flex items-center gap-sm">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={
              filter === f
                ? "rounded-full bg-secondary-container px-md py-1 font-body-sm text-body-sm font-semibold text-on-secondary-container"
                : "rounded-full px-md py-1 font-body-sm text-body-sm text-on-surface-variant hover:bg-surface-container-high"
            }
          >
            {f === "open" ? "Open findings" : "All results"}
          </button>
        ))}
        {findings && (
          <span className="font-body-sm text-body-sm text-on-surface-variant">
            {visible.length} of {findings.length}
          </span>
        )}
      </div>

      <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-outline-variant bg-surface-container-low">
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Severity</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Control</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Resource</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Outcome</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Category</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant">Evaluated</th>
                <th className="p-sm font-label-caps text-label-caps font-semibold uppercase text-on-surface-variant"></th>
              </tr>
            </thead>
            <tbody className="font-body-md text-body-md text-on-surface">
              {!findings && Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} cols={7} />)}

              {findings && visible.length === 0 && (
                <tr>
                  <td colSpan={7} className="p-lg text-center">
                    <div className="flex flex-col items-center gap-xs">
                      <Icon name="task_alt" className="text-[28px] text-success" />
                      <p className="font-body-md text-body-md text-on-surface">
                        {filter === "open" ? "No open findings on the latest run." : "No results."}
                      </p>
                    </div>
                  </td>
                </tr>
              )}

              {visible.map((f) => {
                const k = keyOf(f);
                const canRequest = (f.outcome === "fail" || f.outcome === "error") && !f.suppressed;
                const requested = justRequested.has(k);
                return (
                  <Fragment key={f.result_id}>
                    <tr className="group border-b border-outline-variant last:border-0 hover:bg-surface-container-low">
                      <td className="p-sm"><SeverityBadge severity={f.severity} /></td>
                      <td className="p-sm">
                        <div className="font-data-mono text-data-mono text-on-surface">{f.control_id}</div>
                        <div className="font-body-sm text-body-sm text-on-surface-variant">{f.title}</div>
                      </td>
                      <td className="p-sm font-data-mono text-data-mono">{f.resource_id}</td>
                      <td className="p-sm"><OutcomeIndicator outcome={f.outcome} /></td>
                      <td className="p-sm capitalize">{f.category.replace(/_/g, " ")}</td>
                      <td className="p-sm font-body-sm text-body-sm text-on-surface-variant">
                        {new Date(f.evaluated_at).toLocaleString()}
                      </td>
                      <td className="p-sm text-right">
                        <div className="flex items-center justify-end gap-xs">
                          <button
                            onClick={() => setExpandedEvidence(expandedEvidence === f.result_id ? null : f.result_id)}
                            className="rounded p-1 text-on-surface-variant hover:bg-surface-container-high"
                            aria-label="Show evidence"
                          >
                            <Icon name={expandedEvidence === f.result_id ? "expand_less" : "expand_more"} />
                          </button>
                          {f.suppressed && <SeverityBadgeless label="suppressed" />}
                          {requested && <SeverityBadgeless label="pending review" />}
                          {canRequest && !requested && (
                            <button
                              onClick={() => setRequestingFor(requestingFor === f.result_id ? null : f.result_id)}
                              className="rounded border border-outline-variant px-sm py-1 font-body-sm text-body-sm text-on-surface hover:bg-surface-container-high"
                            >
                              Request exception
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {expandedEvidence === f.result_id && (
                      <tr className="bg-surface-container-low">
                        <td colSpan={7} className="p-md">
                          <div className="flex flex-col gap-xs rounded border border-outline-variant bg-surface p-sm">
                            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Evidence</span>
                            <pre className="overflow-x-auto whitespace-pre-wrap break-all font-data-mono text-data-mono text-on-surface">
                              {JSON.stringify(f.evidence, null, 2)}
                            </pre>
                            <span className="mt-xs font-label-caps text-label-caps uppercase text-on-surface-variant">Remediation</span>
                            <p className="font-body-sm text-body-sm text-on-surface-variant">{f.remediation}</p>
                          </div>
                        </td>
                      </tr>
                    )}
                    {requestingFor === f.result_id && (
                      <RequestExceptionForm
                        finding={f}
                        onCancel={() => setRequestingFor(null)}
                        onDone={() => {
                          setJustRequested((s) => new Set(s).add(k));
                          setRequestingFor(null);
                          reload(); // so Exceptions (and the Overview count) show it now
                        }}
                      />
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SeverityBadgeless({ label }: { label: string }) {
  return (
    <span className="whitespace-nowrap rounded-full bg-surface-container-high px-sm py-0.5 font-body-sm text-body-sm text-on-surface-variant">
      {label}
    </span>
  );
}
