"""
Phase 4 verification: exception workflow, separation of duties, and expiry.

Every check here runs against the live PostgreSQL database and real `results` rows
from real scans. Nothing is mocked, and the expiry check is not called in isolation —
expiry is demonstrated by creating an exception with a real near-term `expiry_date`,
observing the finding suppressed, letting the clock pass it, running a real scan, and
observing the finding return.

Usage:
    python tests/verify_phase4.py --sod
    python tests/verify_phase4.py --request CIS-1.4.2 --expires-in 120 \
        --requester aravind --approver priya
    python tests/verify_phase4.py --views
    python tests/verify_phase4.py --expiry-status
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from audit import AuditSink  # noqa: E402
from db import get_engine, get_sessionmaker  # noqa: E402
from exceptions_service import (  # noqa: E402
    ApprovalError,
    accepted_risks,
    approve_exception,
    expired_exceptions,
    open_findings,
    request_exception,
)
from queries import latest_completed_run  # noqa: E402

import uuid  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))
        _failures.append(label)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def test_separation_of_duties() -> None:
    """A high/critical exception must not be self-approved. A medium one may be."""
    engine = get_engine()
    Session = get_sessionmaker(engine)

    print("\n=== Separation of duties (enforced, not merely documented) ===\n")

    # --- critical control, self-approval must be REFUSED ---------------------
    with Session() as s:
        sink = AuditSink(s, uuid.uuid4(), None, actor="aravind")
        exc_id = request_exception(
            s, "CIS-1.4.2", "linux_server:demo-ubuntu-vagrant",
            requested_by="aravind",
            justification="SoD test: self-approval on a critical control must fail.",
            expiry_date=_now() + datetime.timedelta(days=7),
            audit_sink=sink,
        )
        s.commit()

    with Session() as s:
        sink = AuditSink(s, uuid.uuid4(), None, actor="aravind")
        try:
            approve_exception(s, exc_id, approved_by="aravind", audit_sink=sink)
            s.commit()
            check("critical: self-approval REFUSED", False, "it was allowed")
        except ApprovalError as e:
            s.commit()  # the denial audit row still persists
            check("critical: self-approval REFUSED", True, str(e)[:60] + "...")

    # case/whitespace must not defeat the rule
    with Session() as s:
        try:
            approve_exception(s, exc_id, approved_by="  Aravind ")
            check("critical: 'Aravind ' cannot bypass via case/whitespace", False,
                  "it was allowed")
        except ApprovalError:
            check("critical: 'Aravind ' cannot bypass via case/whitespace", True)

    # the row must still be unapproved after the refusals
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT status, approved_by FROM exceptions WHERE exception_id=:e"),
            {"e": exc_id}).mappings().one()
    check("refused approval left the row unapproved",
          row["approved_by"] is None and row["status"] == "pending_review",
          f"status={row['status']} approved_by={row['approved_by']}")

    # --- distinct approver must SUCCEED --------------------------------------
    with Session() as s:
        sink = AuditSink(s, uuid.uuid4(), None, actor="priya")
        approve_exception(s, exc_id, approved_by="priya", audit_sink=sink)
        s.commit()
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT status, approved_by, approval_date FROM exceptions "
            "WHERE exception_id=:e"), {"e": exc_id}).mappings().one()
    check("critical: distinct approver ACCEPTED",
          row["approved_by"] == "priya" and row["status"] == "accepted_risk",
          f"approved_by={row['approved_by']} status={row['status']}")
    check("approval_date recorded", row["approval_date"] is not None)

    # --- double approval must be refused -------------------------------------
    with Session() as s:
        try:
            approve_exception(s, exc_id, approved_by="someone-else")
            check("already-approved exception cannot be re-approved", False)
        except ApprovalError:
            check("already-approved exception cannot be re-approved", True)

    # --- medium severity: self-approval is permitted by spec -----------------
    with Session() as s:
        med_id = request_exception(
            s, "CIS-5.3.1", "linux_server:demo-ubuntu-vagrant",
            requested_by="aravind",
            justification="SoD test: medium severity may be self-approved per spec.",
            expiry_date=_now() + datetime.timedelta(days=7),
        )
        s.commit()
    with Session() as s:
        try:
            approve_exception(s, med_id, approved_by="aravind")
            s.commit()
            check("medium: self-approval ALLOWED (spec limits SoD to high/critical)", True)
        except ApprovalError as e:
            check("medium: self-approval ALLOWED", False, str(e))

    # clean up the medium one so it does not pollute later views
    with Session() as s:
        s.execute(text("DELETE FROM exceptions WHERE exception_id=:e"), {"e": med_id})
        s.commit()
    print("\n  (medium-severity test exception deleted; exceptions is not an "
          "append-only table, unlike results/audit_log)")


def do_request(control_id: str, expires_in: int, requester: str, approver: str) -> None:
    engine = get_engine()
    Session = get_sessionmaker(engine)
    expiry = _now() + datetime.timedelta(seconds=expires_in)

    with Session() as s:
        sink = AuditSink(s, uuid.uuid4(), None, actor=requester)
        exc_id = request_exception(
            s, control_id, "linux_server:demo-ubuntu-vagrant",
            requested_by=requester,
            justification=(
                "Phase 4 expiry demonstration: short-lived accepted risk created "
                "with a real near-term expiry_date to prove automatic lapse."
            ),
            expiry_date=expiry,
            compensating_control="Host is on an isolated host-only network.",
            audit_sink=sink,
        )
        approve_exception(s, exc_id, approved_by=approver, audit_sink=sink)
        s.commit()

    print(f"exception_id : {exc_id}")
    print(f"control      : {control_id}")
    print(f"requested_by : {requester}")
    print(f"approved_by  : {approver}")
    print(f"expiry_date  : {expiry.isoformat()}  (in {expires_in}s)")


def show_views() -> None:
    engine = get_engine()
    with engine.connect() as c:
        run = latest_completed_run(c)
        now = _now()
        openf = open_findings(c, run, now)
        accepted = accepted_risks(c, run, now)

        print(f"\nlatest completed run : {run}")
        print(f"as of                : {now.isoformat()}")

        total_fail = c.execute(text(
            "SELECT count(*) FROM results WHERE run_id=:r AND outcome='fail'"),
            {"r": run}).scalar()

        print(f"\ntotal failing results in run : {total_fail}")
        print(f"OPEN FINDINGS                : {len(openf)}")
        print(f"ACCEPTED RISK                : {len(accepted)}")
        check("open + accepted == total failing (no finding lost or double-counted)",
              len(openf) + len(accepted) == total_fail,
              f"{len(openf)} + {len(accepted)} vs {total_fail}")

        if accepted:
            print("\nACCEPTED RISK view:")
            print(f"  {'CONTROL':<12} {'SEV':<9} {'RESULT':<7} {'REQ':<10} {'APPR':<10} EXPIRES")
            for r in accepted:
                print(f"  {r['control_id']:<12} {r['severity']:<9} {r['outcome']:<7} "
                      f"{r['requested_by']:<10} {r['approved_by']:<10} "
                      f"{str(r['expiry_date'])[:19]}")
            check("suppressed findings are still stored as 'fail' in results",
                  all(r["outcome"] == "fail" for r in accepted),
                  "an exception must never rewrite the evidence")

        suppressed = {r["control_id"] for r in accepted}
        open_ids = {r["control_id"] for r in openf}
        if suppressed:
            check("suppressed controls absent from OPEN FINDINGS",
                  not (suppressed & open_ids), str(suppressed & open_ids))


def show_expiry_status() -> None:
    engine = get_engine()
    with engine.connect() as c:
        now = _now()
        expired = expired_exceptions(c, now)
        print(f"\nas of {now.isoformat()}")
        print(f"expired (approved but lapsed) exceptions: {len(expired)}")
        for e in expired:
            print(f"  {e['control_id']:<12} [{e['severity']:<8}] approved_by="
                  f"{e['approved_by']:<8} expired {str(e['expiry_date'])[:19]}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sod", action="store_true")
    p.add_argument("--request")
    p.add_argument("--expires-in", type=int, default=120)
    p.add_argument("--requester", default="aravind")
    p.add_argument("--approver", default="priya")
    p.add_argument("--views", action="store_true")
    p.add_argument("--expiry-status", action="store_true")
    a = p.parse_args()

    if a.sod:
        test_separation_of_duties()
    elif a.request:
        do_request(a.request, a.expires_in, a.requester, a.approver)
    elif a.views:
        show_views()
    elif a.expiry_status:
        show_expiry_status()
    else:
        p.error("choose --sod, --request, --views or --expiry-status")

    if _failures:
        print(f"\n{len(_failures)} CHECK(S) FAILED: {_failures}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
