"use client";

import Image from "next/image";

import Avatar from "./Avatar";
import Icon from "./Icon";
import ScanProgressBar from "./ScanProgressBar";
import { useDashboard } from "../lib/dashboard-context";

/**
 * ONE header layout, used identically on every page. Reconciled from the five
 * mockups: Overview put the mobile logo + a spacer on the left, History/Runs put
 * the page title there instead, and Exceptions additionally rendered a second,
 * redundant top-tab nav duplicating the sidebar. The page-title version is adopted
 * (more useful, and the only one that doesn't repeat the sidebar's own logo) and
 * the redundant tab nav is dropped -- sidebar is the only navigation, everywhere.
 *
 * `title` is the only thing that differs page to page; everything else (identity,
 * scan control) is identical because it is the SAME shared context on every page.
 */
export default function Header({ title }: { title: string }) {
  const { data, runScan, scanning, scanProgress, logout } = useDashboard();

  return (
    <header className="sticky top-0 z-30 flex flex-col gap-sm border-b border-outline-variant bg-surface-container-lowest px-lg py-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-sm">
          <Image src="/audittool_logo.png" alt="AuditTool" width={24} height={24} className="rounded md:hidden" />
          <h2 className="font-headline-sm text-headline-sm text-primary">{title}</h2>
        </div>

        <div className="flex items-center gap-md">
          <button
            // 15 targets, not the default 1: a single target finishes in ~7s, almost
            // entirely inside the collection phase, so there's nothing to actually
            // SEE progress on. This reuses the same clone-target mechanism Phase 8
            // built for scale validation (distinct resource_ids against the same
            // demo VM, documented there as an orchestration/DB/UI test, not 15
            // independent real hosts) purely so the live progress mechanism has
            // enough real wall-clock time to be visibly demonstrated.
            onClick={() => runScan("live", 15)}
            disabled={scanning}
            className="flex items-center gap-xs rounded bg-primary px-md py-sm font-body-sm text-body-sm font-semibold text-on-primary hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Icon name="scan" className={`text-[18px] ${scanning ? "animate-pulse" : ""}`} />
            {scanning ? "Scanning…" : "Run Scan"}
          </button>

          <div className="flex items-center gap-sm border-l border-outline-variant pl-md">
            {data && <Avatar username={data.viewer} size={32} />}
            <span className="hidden font-body-sm text-body-sm text-on-surface sm:block">
              {data?.viewer ?? ""}
            </span>
            <button
              onClick={logout}
              className="rounded px-2 py-1 font-body-sm text-body-sm text-on-surface-variant hover:bg-surface-container-high"
            >
              Sign out
            </button>
          </div>
        </div>
      </div>

      {/* Real progress, not a spinner: appears the instant a scan is triggered and
          reflects GET /api/scans/{run_id} on every tick, visible on every page since
          Header is shared -- you can navigate away from Overview mid-scan and still
          see it climbing. */}
      {scanProgress && (
        <div className="animate-[fadeIn_200ms_ease-out]">
          <ScanProgressBar progress={scanProgress} />
        </div>
      )}
    </header>
  );
}
