"use client";

import { useState } from "react";

import { SeverityBadge, StatusPill } from "./Badges";
import Icon from "./Icon";
import { SkeletonBlock } from "./Skeleton";
import { API, useDashboard, type Exc } from "../lib/dashboard-context";

const GROUPS: { key: string; label: string; match: (e: Exc) => boolean }[] = [
  { key: "pending", label: "Pending review", match: (e) => e.status === "pending_review" },
  { key: "accepted", label: "Accepted risk", match: (e) => e.status === "accepted_risk" && !e.expired },
  { key: "expired", label: "Expired", match: (e) => e.expired },
  { key: "false_positive", label: "False positive", match: (e) => e.status === "false_positive" },
];

function expiryTone(e: Exc): "success" | "warning" | "error" | "neutral" {
  if (e.expired) return "error";
  if (e.days_until_expiry !== null && e.days_until_expiry <= 7) return "warning";
  return "success";
}

function Row({ exc, onApproved }: { exc: Exc; onApproved: () => void }) {
  const { data } = useDashboard();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const isPending = exc.status === "pending_review";
  const isOwnRequest = data?.viewer === exc.requested_by;

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/exceptions/${exc.exception_id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: "accepted_risk" }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) { setError(body.detail ?? `HTTP ${r.status}`); return; }
      onApproved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-b border-outline-variant last:border-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-md px-md py-sm text-left hover:bg-surface-container-low"
      >
        <SeverityBadge severity={exc.severity} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-data-mono text-data-mono text-on-surface">{exc.control_id}</div>
          <div className="truncate font-body-sm text-body-sm text-on-surface-variant">{exc.title}</div>
        </div>
        <StatusPill tone={expiryTone(exc)}>
          {exc.expired ? "Expired" : exc.days_until_expiry !== null ? `${exc.days_until_expiry}d left` : "—"}
        </StatusPill>
        <Icon name={open ? "expand_less" : "expand_more"} className="text-on-surface-variant" />
      </button>

      {open && (
        <div className="animate-[fadeIn_150ms_ease-out] flex flex-col gap-sm border-t border-outline-variant bg-surface-container-low px-md py-sm">
          <div className="grid grid-cols-2 gap-sm font-body-sm text-body-sm sm:grid-cols-4">
            <div><span className="text-on-surface-variant">Resource</span><div className="font-data-mono text-data-mono">{exc.resource_id ?? "—"}</div></div>
            <div><span className="text-on-surface-variant">Requested by</span><div>{exc.requested_by}</div></div>
            <div><span className="text-on-surface-variant">Approved by</span><div>{exc.approved_by ?? "—"}</div></div>
            <div><span className="text-on-surface-variant">Expires</span><div>{new Date(exc.expiry_date).toLocaleDateString()}</div></div>
          </div>
          <div>
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">Justification</span>
            <p className="font-body-sm text-body-sm text-on-surface">{exc.justification}</p>
          </div>

          {error && (
            <p className="rounded border border-error-container bg-error-container px-sm py-1 font-body-sm text-body-sm text-on-error-container">
              {error}
            </p>
          )}

          {isPending && (
            <div className="flex items-center gap-sm">
              <button
                onClick={approve} disabled={busy}
                className="rounded bg-primary px-md py-sm font-body-sm text-body-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-50"
              >
                {busy ? "Approving…" : "Approve"}
              </button>
              {isOwnRequest && (
                <span className="font-body-sm text-body-sm text-on-surface-variant">
                  You requested this — approving it yourself will be rejected for high/critical
                  controls (separation of duties).
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ExceptionsContent() {
  const { data, reload } = useDashboard();

  if (!data) {
    return (
      <div className="flex flex-col gap-md">
        {[0, 1].map((i) => (
          <div key={i} className="rounded-lg border border-outline-variant bg-surface-container-lowest p-md">
            <SkeletonBlock className="mb-sm h-4 w-40" />
            <SkeletonBlock className="h-10 w-full" />
          </div>
        ))}
      </div>
    );
  }

  const groups = GROUPS.map((g) => ({ ...g, rows: data.exceptions.filter(g.match) })).filter((g) => g.rows.length > 0);

  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center gap-sm rounded-lg border border-outline-variant bg-surface-container-lowest p-lg text-center">
        <Icon name="verified" className="text-[28px] text-success" />
        <p className="font-body-md text-body-md text-on-surface">No exceptions on record.</p>
        <p className="font-body-sm text-body-sm text-on-surface-variant">
          Request one from a failing control on the Findings page.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-lg">
      {groups.map((g) => (
        <section key={g.key} className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
          <div className="border-b border-outline-variant bg-surface-container p-md">
            <h3 className="font-headline-sm text-headline-sm text-primary">
              {g.label} <span className="font-body-sm text-body-sm text-on-surface-variant">({g.rows.length})</span>
            </h3>
          </div>
          {g.rows.map((exc) => <Row key={exc.exception_id} exc={exc} onApproved={reload} />)}
        </section>
      ))}
    </div>
  );
}
