import Icon from "./Icon";

/**
 * RECONCILIATION NOTE.
 *
 * The five mockups used THREE different severity palettes (Overview's severity-
 * breakdown dots, the Findings table's badges, and History's finding-count chips
 * all used different hex values for the same four severities) and TWO different
 * status-pill palettes (Runs vs. Exceptions used different ad hoc hex for
 * conceptually similar states). None of that was one design system -- it was three
 * mockups that happened to share a nav.
 *
 * The Findings table's severity badge treatment is adopted as canonical (it is the
 * most legible token-backed pairing, not raw hex) and applied everywhere severity
 * appears. One deliberate note on fidelity: their system pairs MEDIUM with a blue
 * token (secondary-fixed/on-secondary-fixed-variant) rather than the amber most
 * security tools use for medium. That reads unusually at first glance, but the brief
 * was to adopt their system, not correct its color psychology, so it is kept as
 * extracted rather than silently "fixed."
 */
const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-error-container text-on-error-container",
  high: "bg-tertiary-fixed text-on-tertiary-fixed-variant",
  medium: "bg-secondary-fixed text-on-secondary-fixed-variant",
  low: "bg-surface-container-high text-on-surface-variant",
};

export function SeverityBadge({ severity }: { severity: string }) {
  const style = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.low;
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${style}`}>
      {severity}
    </span>
  );
}

/** Same severity scale, as a small dot rather than a filled pill (dense contexts). */
export function SeverityDot({ severity }: { severity: string }) {
  const dot: Record<string, string> = {
    critical: "bg-on-error-container", high: "bg-on-tertiary-fixed-variant",
    medium: "bg-on-secondary-fixed-variant", low: "bg-outline",
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${dot[severity] ?? dot.low}`} />;
}

/**
 * Status pill -- the rounded, dotted pill pattern from the Runs and Exceptions
 * mockups (adopted over Findings' plain icon+text row style, since a named,
 * reusable pill is the more useful shared component). `tone` is the caller's job:
 * each page maps its own domain status (pass/fail/error, running/completed/failed,
 * active/expired) onto one of these four, which keeps this component generic
 * rather than hardcoding any one page's vocabulary into it.
 */
const TONE_STYLE: Record<string, string> = {
  success: "bg-success-container text-success",
  error: "bg-error-container text-on-error-container",
  warning: "bg-tertiary-fixed text-on-tertiary-fixed-variant",
  neutral: "bg-surface-container-high text-on-surface-variant",
};

export function StatusPill({ tone, children, pulse = false }: {
  tone: "success" | "error" | "warning" | "neutral"; children: React.ReactNode; pulse?: boolean;
}) {
  const dotColor: Record<string, string> = {
    success: "bg-success", error: "bg-on-error-container",
    warning: "bg-on-tertiary-fixed-variant", neutral: "bg-outline",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${TONE_STYLE[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dotColor[tone]} ${pulse ? "animate-pulse" : ""}`} />
      {children}
    </span>
  );
}

/** Control-outcome indicator (pass/fail/error/manual_review) -- icon+text, from Findings. */
const OUTCOME: Record<string, { icon: string; filled: boolean; className: string; label: string }> = {
  pass: { icon: "check_circle", filled: true, className: "text-on-surface-variant", label: "Pass" },
  fail: { icon: "cancel", filled: true, className: "text-error", label: "Fail" },
  error: { icon: "error", filled: true, className: "text-on-secondary-container", label: "Error" },
  manual_review: { icon: "do_not_disturb_on", filled: false, className: "text-on-surface-variant", label: "Manual review" },
};

export function OutcomeIndicator({ outcome }: { outcome: string }) {
  const o = OUTCOME[outcome] ?? OUTCOME.manual_review;
  return (
    <span className={`inline-flex items-center gap-xs font-medium ${o.className}`}>
      <Icon name={o.icon} filled={o.filled} className="text-[16px]" />
      {o.label}
    </span>
  );
}
