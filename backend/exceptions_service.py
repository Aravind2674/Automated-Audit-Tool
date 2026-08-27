"""
Exception workflow: request, approve, and expiry.

An exception never changes a `results` row. Results are append-only and record what
the host actually looked like at scan time; an accepted risk does not make a failing
control pass. Exceptions are applied as a *filter over the view* — a suppressed
finding still exists as a `fail` in the evidence, it is merely presented under
"accepted risk" instead of "open findings".

That distinction is what keeps the audit trail honest. If an approved exception
rewrote the result to `pass`, the compliance percentage would improve because someone
signed a form, and there would be no record that the underlying control was ever
failing.

Two rules from spec Section 3 are enforced here rather than merely documented:

1.  **Separation of duties.** For `high` and `critical` severity controls, the
    approver must be a different identity from the requester. This is enforced in
    `approve_exception` and raises `ApprovalError`; it is not a comment or a
    convention someone can forget.

2.  **No permanent exceptions, ever.** `expiry_date` is NOT NULL in the schema, and
    an exception whose expiry has passed stops suppressing its finding automatically
    on the next scan. Nothing needs to run on a schedule to make that happen — the
    filter is evaluated at query time against the current clock, so an expired
    exception simply stops matching.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import text

from models.schema import Control, Exception_

#: Severities for which the approver must differ from the requester.
SEPARATION_OF_DUTIES_SEVERITIES = {"high", "critical"}

#: Statuses that actively suppress a finding once approved.
SUPPRESSING_STATUSES = ("accepted_risk", "false_positive")


class ExceptionWorkflowError(Exception):
    """Base class for exception-workflow rule violations."""


class ApprovalError(ExceptionWorkflowError):
    """Raised when an approval violates separation of duties or workflow state."""


class ExpiryError(ExceptionWorkflowError):
    """Raised when an exception is created without a usable expiry date."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def request_exception(
    session,
    control_id: str,
    resource_id: str,
    requested_by: str,
    justification: str,
    expiry_date: datetime.datetime,
    status: str = "accepted_risk",
    compensating_control: str | None = None,
    audit_sink=None,
) -> uuid.UUID:
    """Create a pending exception request. Returns the new exception_id.

    The requested final status (`accepted_risk` or `false_positive`) is recorded, but
    the exception does not suppress anything until it is approved -- `approved_by`
    stays NULL and the suppression filter requires it to be set.
    """
    if status not in SUPPRESSING_STATUSES:
        raise ExceptionWorkflowError(
            f"status must be one of {SUPPRESSING_STATUSES}, got {status!r}"
        )
    if expiry_date is None:
        raise ExpiryError("expiry_date is required -- no permanent exceptions, ever")
    if not justification or not justification.strip():
        raise ExceptionWorkflowError("justification is required")

    control = session.get(Control, control_id)
    if control is None:
        raise ExceptionWorkflowError(f"unknown control_id {control_id!r}")

    exception_id = uuid.uuid4()
    session.add(
        Exception_(
            exception_id=exception_id,
            control_id=control_id,
            resource_id=resource_id,
            # Stored as pending_review until an approver acts. The requested end
            # state is carried in the justification trail, not pre-applied.
            status="pending_review",
            justification=justification,
            requested_by=requested_by,
            approved_by=None,
            approval_date=None,
            expiry_date=expiry_date,
            compensating_control=compensating_control,
        )
    )

    if audit_sink is not None:
        audit_sink.write(
            {
                "event_type": "exception_requested",
                "result": "pending_review",
                "actor": requested_by,
                "details": {
                    "exception_id": str(exception_id),
                    "control_id": control_id,
                    "resource_id": resource_id,
                    "severity": control.severity,
                    "requested_status": status,
                    "expiry_date": expiry_date.isoformat(),
                },
            }
        )
    return exception_id


def approve_exception(
    session,
    exception_id: uuid.UUID,
    approved_by: str,
    status: str = "accepted_risk",
    audit_sink=None,
) -> None:
    """Approve a pending exception.

    Raises ApprovalError if the control's severity is high or critical and the
    approver is the same identity as the requester.
    """
    if status not in SUPPRESSING_STATUSES:
        raise ExceptionWorkflowError(
            f"status must be one of {SUPPRESSING_STATUSES}, got {status!r}"
        )

    exc = session.get(Exception_, exception_id)
    if exc is None:
        raise ApprovalError(f"unknown exception_id {exception_id}")
    if exc.approved_by is not None:
        raise ApprovalError(f"exception {exception_id} is already approved")

    control = session.get(Control, exc.control_id)
    if control is None:
        raise ApprovalError(f"unknown control_id {exc.control_id!r}")

    # --- separation of duties -------------------------------------------------
    if control.severity in SEPARATION_OF_DUTIES_SEVERITIES:
        # Compared case-insensitively and whitespace-trimmed so that "Aravind" and
        # "aravind " cannot be used to slip past the rule.
        if exc.requested_by.strip().lower() == approved_by.strip().lower():
            if audit_sink is not None:
                audit_sink.write(
                    {
                        "event_type": "exception_approval_denied",
                        "result": "denied",
                        "actor": approved_by,
                        "details": {
                            "exception_id": str(exception_id),
                            "control_id": exc.control_id,
                            "severity": control.severity,
                            "reason": "separation of duties: approver must differ "
                                      "from requester for high/critical severity",
                        },
                    }
                )
            raise ApprovalError(
                f"separation of duties: control {exc.control_id} is severity "
                f"{control.severity!r}, so the approver must be a different identity "
                f"from the requester ({exc.requested_by!r})"
            )

    exc.status = status
    exc.approved_by = approved_by
    exc.approval_date = _now()

    if audit_sink is not None:
        audit_sink.write(
            {
                "event_type": "exception_approved",
                "result": status,
                "actor": approved_by,
                "details": {
                    "exception_id": str(exception_id),
                    "control_id": exc.control_id,
                    "resource_id": exc.resource_id,
                    "severity": control.severity,
                    "requested_by": exc.requested_by,
                    "approved_by": approved_by,
                    "expiry_date": exc.expiry_date.isoformat(),
                },
            }
        )


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

#: An exception suppresses a finding only when ALL of these hold:
#:   * it has been approved (approved_by IS NOT NULL)
#:   * its status is a suppressing one (not still pending_review)
#:   * its expiry_date is still in the future
#:
#: Expiry is evaluated at query time against the current clock, so an exception
#: lapses on its own. There is no scheduled job to forget to run.
_ACTIVE_EXCEPTION = """
    SELECT 1 FROM exceptions e
     WHERE e.control_id  = res.control_id
       AND e.resource_id = res.resource_id
       AND e.approved_by IS NOT NULL
       AND e.status IN ('accepted_risk', 'false_positive')
       AND e.expiry_date > :as_of
"""

OPEN_FINDINGS_SQL = f"""
SELECT res.control_id, res.resource_id, c.severity, c.title, res.outcome
FROM results res JOIN controls c ON c.id = res.control_id
WHERE res.run_id = :run_id
  AND res.outcome = 'fail'
  AND NOT EXISTS ({_ACTIVE_EXCEPTION})
ORDER BY CASE c.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                         WHEN 'medium' THEN 2 ELSE 3 END,
         res.control_id, res.resource_id
"""

#: One row per SUPPRESSED FINDING, not per matching exception.
#:
#: Bug found in Phase 8: this was a plain JOIN, so a finding covered by more than one
#: active exception produced one row per exception. Nothing is stopping several
#: exceptions covering the same (control, resource) -- repeated requests, overlapping
#: approvals, a re-request before the previous one lapsed -- and the dashboard's
#: "accepted risk" count was inflated accordingly, breaking the
#: `open + accepted == total failing` invariant.
#:
#: DISTINCT ON collapses them to one row per finding, keeping the exception that
#: expires LAST, since that is the one actually governing how long the suppression
#: lasts.
ACCEPTED_RISK_SQL = f"""
SELECT DISTINCT ON (res.control_id, res.resource_id)
       res.control_id, res.resource_id, c.severity, res.outcome,
       e.exception_id, e.status, e.requested_by, e.approved_by,
       e.expiry_date, e.justification
FROM results res
JOIN controls c ON c.id = res.control_id
JOIN exceptions e ON e.control_id = res.control_id
                 AND e.resource_id = res.resource_id
WHERE res.run_id = :run_id
  AND res.outcome = 'fail'
  AND e.approved_by IS NOT NULL
  AND e.status IN ('accepted_risk', 'false_positive')
  AND e.expiry_date > :as_of
ORDER BY res.control_id, res.resource_id, e.expiry_date DESC
"""

EXPIRED_EXCEPTIONS_SQL = """
SELECT e.exception_id, e.control_id, c.severity, e.approved_by, e.expiry_date
FROM exceptions e JOIN controls c ON c.id = e.control_id
WHERE e.approved_by IS NOT NULL AND e.expiry_date <= :as_of
ORDER BY e.expiry_date
"""


def open_findings(conn, run_id, as_of: datetime.datetime | None = None) -> list[dict]:
    """Failing controls in a run that are NOT covered by an active exception."""
    return [
        dict(r)
        for r in conn.execute(
            text(OPEN_FINDINGS_SQL), {"run_id": run_id, "as_of": as_of or _now()}
        ).mappings()
    ]


def accepted_risks(conn, run_id, as_of: datetime.datetime | None = None) -> list[dict]:
    """Failing controls in a run that ARE covered by an active exception."""
    return [
        dict(r)
        for r in conn.execute(
            text(ACCEPTED_RISK_SQL), {"run_id": run_id, "as_of": as_of or _now()}
        ).mappings()
    ]


def expired_exceptions(conn, as_of: datetime.datetime | None = None) -> list[dict]:
    """Approved exceptions whose expiry has passed and which no longer suppress."""
    return [
        dict(r)
        for r in conn.execute(
            text(EXPIRED_EXCEPTIONS_SQL), {"as_of": as_of or _now()}
        ).mappings()
    ]
