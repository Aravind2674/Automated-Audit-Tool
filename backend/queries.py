"""
Historical and drift queries over the append-only results table.

Everything here is READ-ONLY. `results` and `audit_log` are insert-only (spec
Section 3), so history is derived by querying accumulated runs rather than by
maintaining any separate current-state or changelog table that could disagree with
the evidence.

Two consequences that shape these queries:

* "Current compliance posture" is always *"results where run_id = the latest
  completed run"*. There is no current-state table to read instead.
* Drift is computed by comparing two runs' result sets. It is not recorded at write
  time, so a drift report can be regenerated for any pair of historical runs, and
  it can never drift out of sync with the results it describes.
"""

from __future__ import annotations

from sqlalchemy import text

#: Compliance % per run over time.
#:
#: `manual_review` and `error` are excluded from the denominator deliberately. A
#: control awaiting human judgement has not passed and has not failed, and an
#: unreadable source is a broken audit rather than a compliance failure -- counting
#: either as a failure would make the percentage move for reasons that have nothing
#: to do with the host's security posture. They are returned as separate counts so a
#: reader can see they exist rather than having them silently disappear.
COMPLIANCE_TREND_SQL = """
SELECT
    r.run_id,
    r.started_at,
    r.completed_at,
    r.triggered_by,
    count(*)                                                  AS total,
    count(*) FILTER (WHERE res.outcome = 'pass')              AS passed,
    count(*) FILTER (WHERE res.outcome = 'fail')              AS failed,
    count(*) FILTER (WHERE res.outcome = 'error')             AS errored,
    count(*) FILTER (WHERE res.outcome = 'manual_review')     AS manual_review,
    round(
        100.0 * count(*) FILTER (WHERE res.outcome = 'pass')
        / NULLIF(count(*) FILTER (WHERE res.outcome IN ('pass', 'fail')), 0),
        1
    )                                                         AS compliance_pct
FROM runs r
JOIN results res ON res.run_id = r.run_id
WHERE r.status = 'completed'
GROUP BY r.run_id, r.started_at, r.completed_at, r.triggered_by
ORDER BY r.completed_at
"""

#: Per-control outcome change between two runs.
DRIFT_SQL = """
SELECT
    COALESCE(a.control_id, b.control_id)   AS control_id,
    COALESCE(a.resource_id, b.resource_id) AS resource_id,
    c.severity,
    a.outcome                              AS previous_outcome,
    b.outcome                              AS current_outcome
FROM      (SELECT control_id, resource_id, outcome FROM results WHERE run_id = :run_a) a
FULL JOIN (SELECT control_id, resource_id, outcome FROM results WHERE run_id = :run_b) b
       ON a.control_id = b.control_id AND a.resource_id = b.resource_id
LEFT JOIN controls c ON c.id = COALESCE(a.control_id, b.control_id)
WHERE a.outcome IS DISTINCT FROM b.outcome
ORDER BY
    CASE c.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2 ELSE 3 END,
    COALESCE(a.control_id, b.control_id)
"""

LATEST_COMPLETED_RUN_SQL = """
SELECT run_id FROM runs WHERE status = 'completed'
ORDER BY completed_at DESC LIMIT 1
"""


def compliance_trend(conn) -> list[dict]:
    """Compliance % per completed run, oldest first."""
    return [dict(row) for row in conn.execute(text(COMPLIANCE_TREND_SQL)).mappings()]


def latest_completed_run(conn):
    """The run_id whose results constitute current posture, or None."""
    return conn.execute(text(LATEST_COMPLETED_RUN_SQL)).scalar()


def drift_between(conn, run_a, run_b) -> list[dict]:
    """Controls whose outcome differs between run_a and run_b.

    A FULL JOIN is used rather than an inner join so that a control present in only
    one of the two runs still appears, with NULL on the side where it is absent.
    That case matters: a control added to or removed from the library between runs,
    or a resource that dropped out of a scan, is exactly the kind of change a drift
    report must not silently omit.

    `IS DISTINCT FROM` rather than `<>` for the same reason -- `NULL <> 'pass'` is
    NULL, not true, so a plain inequality would discard precisely those rows.
    """
    return [
        dict(row)
        for row in conn.execute(
            text(DRIFT_SQL), {"run_a": run_a, "run_b": run_b}
        ).mappings()
    ]


def classify_drift(rows: list[dict]) -> dict[str, list[dict]]:
    """Split drift rows into improvements, regressions and other transitions."""
    buckets: dict[str, list[dict]] = {
        "improved": [], "regressed": [], "appeared": [], "disappeared": [], "other": []
    }
    for row in rows:
        previous, current = row["previous_outcome"], row["current_outcome"]
        if previous is None:
            buckets["appeared"].append(row)
        elif current is None:
            buckets["disappeared"].append(row)
        elif previous == "fail" and current == "pass":
            buckets["improved"].append(row)
        elif previous == "pass" and current == "fail":
            buckets["regressed"].append(row)
        else:
            # e.g. fail -> error, or manual_review -> fail. Not an improvement or a
            # regression in posture, but still a change worth surfacing.
            buckets["other"].append(row)
    return buckets


# ---------------------------------------------------------------------------
# Dashboard queries (Phase 6)
#
# Every figure the dashboard renders comes from one of these. They are read-only and
# derive everything from the append-only results table -- there is no summary or
# rollup table that could disagree with the evidence it summarises.
#
# Exception suppression is applied consistently with Phase 4: a finding covered by an
# approved, unexpired exception is counted as accepted risk, never silently dropped.
# `open + accepted == total failing` is a property the verification harness asserts.
# ---------------------------------------------------------------------------

#: Shared predicate for "an approved exception currently suppresses this finding".
_ACTIVE_EXC = """
    EXISTS (SELECT 1 FROM exceptions e
             WHERE e.control_id  = res.control_id
               AND e.resource_id = res.resource_id
               AND e.approved_by IS NOT NULL
               AND e.status IN ('accepted_risk','false_positive')
               AND e.expiry_date > :as_of)
"""

DASHBOARD_SUMMARY_SQL = f"""
SELECT
    count(*)                                              AS total,
    count(*) FILTER (WHERE res.outcome = 'pass')          AS passed,
    count(*) FILTER (WHERE res.outcome = 'fail')          AS failed,
    count(*) FILTER (WHERE res.outcome = 'error')         AS errored,
    count(*) FILTER (WHERE res.outcome = 'manual_review') AS manual_review,
    count(*) FILTER (WHERE res.outcome = 'fail' AND NOT {_ACTIVE_EXC})
                                                          AS open_findings,
    count(*) FILTER (WHERE res.outcome = 'fail' AND {_ACTIVE_EXC})
                                                          AS accepted_risk,
    round(
        100.0 * count(*) FILTER (WHERE res.outcome = 'pass')
        / NULLIF(count(*) FILTER (WHERE res.outcome IN ('pass','fail')), 0), 1
    )                                                     AS compliance_pct
FROM results res
WHERE res.run_id = :run_id
"""

PER_DOMAIN_SQL = f"""
SELECT
    c.category,
    count(*)                                              AS total,
    count(*) FILTER (WHERE res.outcome = 'pass')          AS passed,
    count(*) FILTER (WHERE res.outcome = 'fail')          AS failed,
    count(*) FILTER (WHERE res.outcome = 'error')         AS errored,
    count(*) FILTER (WHERE res.outcome = 'fail' AND NOT {_ACTIVE_EXC})
                                                          AS open_findings,
    round(
        100.0 * count(*) FILTER (WHERE res.outcome = 'pass')
        / NULLIF(count(*) FILTER (WHERE res.outcome IN ('pass','fail')), 0), 1
    )                                                     AS compliance_pct
FROM results res
JOIN controls c ON c.id = res.control_id
WHERE res.run_id = :run_id
GROUP BY c.category
ORDER BY c.category
"""

SEVERITY_BREAKDOWN_SQL = f"""
SELECT c.severity,
       count(*) FILTER (WHERE res.outcome = 'fail' AND NOT {_ACTIVE_EXC}) AS open_findings
FROM results res
JOIN controls c ON c.id = res.control_id
WHERE res.run_id = :run_id
GROUP BY c.severity
"""

OPEN_EXCEPTIONS_SQL = """
SELECT e.exception_id, e.control_id, c.severity, c.title,
       e.resource_id, e.status, e.requested_by, e.approved_by,
       e.approval_date, e.expiry_date, e.justification, e.compensating_control,
       (e.expiry_date <= :as_of) AS expired,
       EXTRACT(DAY FROM (e.expiry_date - :as_of))::int AS days_until_expiry
FROM exceptions e
JOIN controls c ON c.id = e.control_id
WHERE e.approved_by IS NOT NULL
ORDER BY e.expiry_date
"""

#: Deliberately separate from OPEN_EXCEPTIONS_SQL, not a widened version of it.
#: open_exceptions() feeds the PDF compliance report (reports/generator.py), where
#: a not-yet-reviewed request must never appear as if it were part of the accepted
#: posture. This is only for the Exceptions page's review queue, which is called out
#: by name in the endpoint that uses it, not folded into "exceptions" generically.
PENDING_EXCEPTIONS_SQL = """
SELECT e.exception_id, e.control_id, c.severity, c.title,
       e.resource_id, e.status, e.requested_by, e.approved_by,
       e.approval_date, e.expiry_date, e.justification, e.compensating_control,
       (e.expiry_date <= :as_of) AS expired,
       EXTRACT(DAY FROM (e.expiry_date - :as_of))::int AS days_until_expiry
FROM exceptions e
JOIN controls c ON c.id = e.control_id
WHERE e.status = 'pending_review'
ORDER BY e.expiry_date
"""

#: Per-finding detail for the PDF export.
#:
#: `evidence` is selected verbatim. The report renders the stored JSONB as-is and does
#: NOT re-run the check, re-derive the values, or paraphrase them into prose. A report
#: that regenerates its own evidence is not evidence -- it is a second opinion that
#: happens to agree, and it would silently diverge from the record the moment the host
#: changed.
FINDINGS_FOR_REPORT_SQL = f"""
SELECT res.result_id, res.control_id, res.resource_id, res.outcome,
       res.evidence, res.evaluated_at,
       c.title, c.severity, c.category, c.remediation, c.framework_mappings,
       {_ACTIVE_EXC} AS suppressed
FROM results res
JOIN controls c ON c.id = res.control_id
WHERE res.run_id = :run_id
ORDER BY
    CASE res.outcome WHEN 'fail' THEN 0 WHEN 'error' THEN 1
                     WHEN 'manual_review' THEN 2 ELSE 3 END,
    CASE c.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2 ELSE 3 END,
    res.control_id, res.resource_id
"""


def _now_utc():
    import datetime

    return datetime.datetime.now(datetime.timezone.utc)


def dashboard_summary(conn, run_id, as_of=None) -> dict:
    row = conn.execute(
        text(DASHBOARD_SUMMARY_SQL), {"run_id": run_id, "as_of": as_of or _now_utc()}
    ).mappings().one()
    return dict(row)


def per_domain_breakdown(conn, run_id, as_of=None) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            text(PER_DOMAIN_SQL), {"run_id": run_id, "as_of": as_of or _now_utc()}
        ).mappings()
    ]


def severity_breakdown(conn, run_id, as_of=None) -> dict:
    rows = conn.execute(
        text(SEVERITY_BREAKDOWN_SQL), {"run_id": run_id, "as_of": as_of or _now_utc()}
    ).mappings()
    return {r["severity"]: r["open_findings"] for r in rows}


def open_exceptions(conn, as_of=None) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            text(OPEN_EXCEPTIONS_SQL), {"as_of": as_of or _now_utc()}
        ).mappings()
    ]


def pending_exceptions(conn, as_of=None) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            text(PENDING_EXCEPTIONS_SQL), {"as_of": as_of or _now_utc()}
        ).mappings()
    ]


def findings_for_report(conn, run_id, as_of=None) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            text(FINDINGS_FOR_REPORT_SQL), {"run_id": run_id, "as_of": as_of or _now_utc()}
        ).mappings()
    ]
