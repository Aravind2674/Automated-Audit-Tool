"""
FastAPI application: dashboard, report export, and the state-changing endpoints.

**Authentication (Phase 7).** Session-based, per spec Section 1. Every endpoint
except `/api/health` and `/api/auth/login` requires a valid session.

The spec requires enforcement on the state-changing endpoints — scan trigger,
exception request/approve, report export. This implementation goes slightly broader
and also protects the read endpoints, because an unauthenticated `/api/dashboard`
discloses the complete compliance posture of every audited host: which controls are
failing, on which resources, with the evidence attached. That is a target list. The
broader scope is noted in BUILD_LOG rather than assumed to be wanted.

Enforcement is a FastAPI dependency (`require_session`) applied per route, not a
middleware that could be bypassed by a route registered before it. `tests/verify_phase7.py`
proves rejection with real unauthenticated HTTP calls rather than by reading the code.
"""

from __future__ import annotations

import datetime
import io
import json
import os
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from fastapi import (  # noqa: E402
    BackgroundTasks, Body, Cookie, Depends, FastAPI, HTTPException, Query, Response,
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from sqlalchemy import text  # noqa: E402

from auth.service import (  # noqa: E402
    SESSION_COOKIE,
    AuthError,
    login as auth_login,
    logout as auth_logout,
    resolve_session,
)
from db import get_engine, get_sessionmaker  # noqa: E402
from queries import (  # noqa: E402
    classify_drift,
    compliance_trend,
    dashboard_summary,
    drift_between,
    findings_for_report,
    latest_completed_run,
    open_exceptions,
    pending_exceptions,
    per_domain_breakdown,
    severity_breakdown,
)

app = FastAPI(
    title="Automated IT Systems Audit Tool",
    description="Compliance dashboard and report API over append-only audit evidence.",
    version="0.7.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


#: Whether to set the `Secure` flag on the session cookie.
#:
#: Environment-conditional rather than hardcoded either way:
#:
#: * Hardcoding True breaks local development outright — browsers refuse to store a
#:   Secure cookie sent over plain http, so login would silently fail on localhost
#:   with no error to explain it.
#: * Hardcoding False is a real vulnerability the moment this is deployed behind TLS:
#:   a session cookie without Secure will be transmitted over an unencrypted
#:   connection if anything ever downgrades the request, handing over the session.
#:
#: Default is False so `git clone && run` works on localhost. **Any real deployment
#: must set SECURE_COOKIES=true**, and the value is echoed in the login response and
#: logged at startup so a misconfigured production instance is visible rather than
#: silently insecure.
SECURE_COOKIES = _env_flag("SECURE_COOKIES", default=False)

#: Max drift rows returned PER CATEGORY. See the dashboard endpoint for why.
DRIFT_ROW_CAP = 100

_Session = None


@app.on_event("startup")
def _warn_if_insecure_cookies() -> None:
    if not SECURE_COOKIES:
        print(
            "[audit-tool] SECURE_COOKIES=false -- session cookies are NOT marked "
            "Secure. Correct for local http development; set SECURE_COOKIES=true "
            "for any deployment behind TLS."
        )


@app.on_event("startup")
def _ensure_schema() -> None:
    """Create tables once at startup.

    Previously each scan trigger called create_schema(), which reflects all eight
    tables and cost ~2.5s per request -- by itself enough to break the sub-second
    trigger the spec requires. Doing it once here is both faster and more correct.
    """
    from db import create_schema
    create_schema(get_engine())


@app.on_event("startup")
def _reap_orphaned_runs() -> None:
    """Mark runs left in 'running' by a previous process as failed.

    Scans execute in FastAPI BackgroundTasks, i.e. in THIS process. A scan therefore
    cannot survive a restart or a crash — so any run still marked `running` when the
    application starts is definitionally dead, not in progress.

    Found during the async re-proof: restarting uvicorn mid-scan left run 55df169b
    stuck on `running` forever, and the dashboard's in-flight banner reported it as an
    active scan indefinitely. A run that never leaves `running` is indistinguishable
    from one still working, so the UI would show a permanently-scanning system with no
    error anywhere — worse than a visible failure.

    This is the honest cost of in-process background execution and is documented as
    such: a real job queue would let a worker resume or explicitly fail the job
    instead. `runs` is not an append-only table, so correcting the status here is
    permitted; the failure is additionally recorded in the append-only audit_log.
    """
    with _sessionmaker()() as s:
        orphans = s.execute(text(
            "SELECT run_id, correlation_id, triggered_by FROM runs "
            "WHERE status = 'running'")).mappings().all()
        for row in orphans:
            s.execute(
                text("UPDATE runs SET status='failed', completed_at=:t "
                     "WHERE run_id=:r"),
                {"t": datetime.datetime.now(datetime.timezone.utc), "r": row["run_id"]},
            )
            _audit(s, row["triggered_by"], "scan_failed", "error",
                   {"reason": "orphaned by application restart -- background task "
                              "cannot survive the process that owns it",
                    "run_id": str(row["run_id"])},
                   correlation_id=row["correlation_id"], run_id=row["run_id"])
        s.commit()
        if orphans:
            print(f"[audit-tool] marked {len(orphans)} orphaned 'running' run(s) as "
                  f"failed on startup")


def _sessionmaker():
    global _Session
    if _Session is None:
        _Session = get_sessionmaker(get_engine())
    return _Session


# ---------------------------------------------------------------------------
# auth dependency
# ---------------------------------------------------------------------------


def require_session(audit_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    """Reject anything without a valid, unexpired session.

    Returns a plain dict rather than an ORM object so the caller does not hold a
    detached instance after the session closes.
    """
    with _sessionmaker()() as s:
        try:
            user = resolve_session(s, audit_session)
            identity = {"username": user.username, "role": user.role}
        except AuthError as exc:
            s.commit()  # persist any expired-session cleanup
            raise HTTPException(
                status_code=401,
                detail=f"authentication required: {exc}",
                headers={"WWW-Authenticate": "Cookie"},
            ) from exc
        s.commit()
    return identity


def _audit(s, actor, event_type, result, details, correlation_id=None, run_id=None):
    s.execute(
        text(
            "INSERT INTO audit_log (event_id, correlation_id, run_id, actor, "
            "event_type, timestamp, result, details) VALUES "
            "(:e, :c, :r, :a, :et, :t, :res, CAST(:d AS jsonb))"
        ),
        {
            "e": str(uuid.uuid4()),
            "c": str(correlation_id or uuid.uuid4()),
            "r": str(run_id) if run_id else None,
            "a": actor,
            "et": event_type,
            "t": datetime.datetime.now(datetime.timezone.utc),
            "res": result,
            "d": json.dumps(details),
        },
    )


def _provider(control_id: str) -> str:
    return "aws" if control_id.startswith("AWS-") else "linux"


def _resolve_run(conn, run_id):
    if run_id:
        return run_id
    run = latest_completed_run(conn)
    if run is None:
        raise HTTPException(404, "no completed runs exist yet")
    return run


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if hasattr(value, "quantize"):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


# ---------------------------------------------------------------------------
# public endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    """Liveness only. Deliberately discloses no compliance data."""
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(response: Response, body: dict = Body(...)) -> dict:
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))
    with _sessionmaker()() as s:
        try:
            session_id = auth_login(s, username, password)
        except AuthError as exc:
            s.commit()  # the login_failed audit row must persist
            raise HTTPException(401, str(exc)) from exc
        s.commit()

    response.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True,        # not readable from JavaScript -> XSS cannot steal it
        samesite="lax",       # not sent on cross-site POSTs -> basic CSRF resistance
        secure=SECURE_COOKIES,  # see the constant's definition
        max_age=8 * 3600,
        path="/",
    )
    return {"status": "ok", "username": username, "secure_cookies": SECURE_COOKIES}


# ---------------------------------------------------------------------------
# authenticated endpoints
# ---------------------------------------------------------------------------


@app.post("/api/auth/logout")
def logout(response: Response, identity=Depends(require_session),
           audit_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict:
    with _sessionmaker()() as s:
        auth_logout(s, audit_session)
        s.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(identity=Depends(require_session)) -> dict:
    return identity


@app.get("/api/dashboard")
def dashboard(run_id: str | None = Query(default=None),
              identity=Depends(require_session)) -> dict:
    with get_engine().connect() as conn:
        run = _resolve_run(conn, run_id)
        summary = dashboard_summary(conn, run)
        domains = per_domain_breakdown(conn, run)
        severities = severity_breakdown(conn, run)
        # The dashboard's exceptions list is a review queue as well as a record of
        # accepted risk, so it includes pending_review rows too -- open_exceptions()
        # alone (approved_by IS NOT NULL) is reused as-is for the PDF report, where a
        # not-yet-reviewed request must never appear as if already accepted.
        exceptions = open_exceptions(conn) + pending_exceptions(conn)
        trend = compliance_trend(conn)

        # Scans still in flight. The dashboard shows the latest COMPLETED run, so
        # without this an async scan would be invisible between trigger and finish --
        # the UI would look idle while work was happening, which is exactly the
        # "silently block or hang" failure the async change is meant to avoid.
        active = [dict(r) for r in conn.execute(text(
            "SELECT run_id, triggered_by, started_at, status FROM runs "
            "WHERE status = 'running' ORDER BY started_at DESC")).mappings()]

        # Drift is CAPPED before serialisation.
        #
        # Phase 8 finding: at 50 targets, drift between two runs with different target
        # sets produced ~1000 rows and 192 KB of JSON -- 97% of the entire dashboard
        # payload -- and it grows linearly with target count. The API answered in
        # 0.1s, so this was never a failure, but shipping an unbounded list to a
        # browser is a defect waiting to become one at 500 targets.
        #
        # The full counts are still reported per category, so nothing is hidden: the
        # UI can say "748 regressed (showing 100)" rather than silently truncating.
        drift, drift_counts, drift_total = [], {}, 0
        if len(trend) >= 2:
            rows = drift_between(conn, trend[-2]["run_id"], trend[-1]["run_id"])
            buckets = classify_drift(rows)
            drift_counts = {kind: len(v) for kind, v in buckets.items() if v}
            drift_total = sum(drift_counts.values())
            for kind, rows_ in buckets.items():
                for row in rows_[:DRIFT_ROW_CAP]:
                    drift.append({"kind": kind, **_jsonable(row)})

    return _jsonable({
        "active_runs": active,
        "run_id": str(run),
        "generated_at": datetime.datetime.now(datetime.timezone.utc),
        "summary": summary, "per_domain": domains,
        "open_findings_by_severity": severities, "exceptions": exceptions,
        "trend": trend,
        "drift_since_previous_run": drift,
        "drift_counts": drift_counts,
        "drift_total": drift_total,
        "drift_row_cap": DRIFT_ROW_CAP,
        "viewer": identity["username"],
    })


@app.get("/api/findings")
def findings(run_id: str | None = Query(default=None),
             identity=Depends(require_session)) -> dict:
    with get_engine().connect() as conn:
        run = _resolve_run(conn, run_id)
        rows = findings_for_report(conn, run)
    return _jsonable({
        "run_id": str(run),
        "findings": [{**r, "provider": _provider(r["control_id"])} for r in rows],
    })


RUNS_ROW_CAP = 100


@app.get("/api/runs")
def list_runs(identity=Depends(require_session)) -> dict:
    """Every run, regardless of outcome -- for the Runs page.

    `compliance_trend` (used on the Overview trend chart) deliberately joins on
    `results` and filters to `status='completed'`, so a failed run -- one that never
    produced a single result row -- silently doesn't appear there at all. That's
    fine for a compliance trend line, where a run with no results has nothing to
    plot, but wrong for a page whose whole purpose is showing what actually
    happened: a failed or still-running scan is a real, current state, not a gap.
    This uses a LEFT JOIN so every run appears, with zero counts where results
    don't exist yet (or never will).
    """
    with get_engine().connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM runs")).scalar()
        rows = [dict(r) for r in conn.execute(text(
            "SELECT r.run_id, r.triggered_by, r.started_at, r.completed_at, r.status, "
            "count(res.result_id) AS total, "
            "count(*) FILTER (WHERE res.outcome = 'pass') AS passed, "
            "count(*) FILTER (WHERE res.outcome = 'fail') AS failed, "
            "count(*) FILTER (WHERE res.outcome = 'error') AS errored, "
            "count(*) FILTER (WHERE res.outcome = 'manual_review') AS manual_review, "
            "round(100.0 * count(*) FILTER (WHERE res.outcome = 'pass') "
            "  / NULLIF(count(*) FILTER (WHERE res.outcome IN ('pass', 'fail')), 0), 1"
            ") AS compliance_pct "
            "FROM runs r LEFT JOIN results res ON res.run_id = r.run_id "
            "GROUP BY r.run_id, r.triggered_by, r.started_at, r.completed_at, r.status "
            "ORDER BY r.started_at DESC LIMIT :cap"),
            {"cap": RUNS_ROW_CAP}).mappings()]
    return _jsonable({"runs": rows, "total": total, "row_cap": RUNS_ROW_CAP})


@app.post("/api/scans", status_code=202)
def trigger_scan(background: BackgroundTasks, body: dict = Body(default={}),
                 identity=Depends(require_session)) -> dict:
    """Trigger a scan. STATE-CHANGING -- requires a session, and is audited.

    **Fires and returns immediately (HTTP 202).** The `runs` row is created
    synchronously with `status='running'`, then collection and evaluation run in a
    FastAPI BackgroundTask in the same process — no Celery, no Redis, no new
    infrastructure, which is the right weight for this deployment's scale.

    This is a direct consequence of Phase 8's measurement: 50 targets took 128.42s of
    sequential SSH, past the default idle timeout of most reverse proxies. Doing that
    inside the request returned a gateway timeout to the browser **while the scan kept
    running server-side** — the user sees failure, retries, and doubles the load
    against the same hosts.

    202 rather than 200 because the work is accepted, not finished. Callers poll
    `GET /api/scans/{run_id}`, or simply watch the dashboard, which reports active
    runs and refreshes while any are in flight.
    """
    from run_scan import create_pending_run, run_pending_scan

    mode = str(body.get("mode", "cached"))
    if mode not in ("cached", "live"):
        raise HTTPException(400, "mode must be 'cached' or 'live'")

    n_targets = int(body.get("targets", 1))
    if not 1 <= n_targets <= 200:
        raise HTTPException(400, "targets must be between 1 and 200")

    if n_targets > 1 and mode != "live":
        raise HTTPException(400, "targets > 1 requires mode='live'")

    # Target RESOLUTION is deliberately left to the background task, not done here.
    #
    # Resolving the demo target shells out to `vagrant ssh-config`, which takes ~7s on
    # this hardware. Doing it in the request made a 50-target trigger return in 7.08s
    # -- a big improvement on 128s, but not the sub-second the spec asks for, and
    # still enough to feel broken behind a proxy. Nothing here should touch the
    # network before the run row exists and the response is on its way.

    try:
        pending = create_pending_run(triggered_by=identity["username"], mode=mode,
                                     targets=n_targets)
    except Exception as exc:  # noqa: BLE001 -- the attempt is audited before raising
        with _sessionmaker()() as s:
            _audit(s, identity["username"], "scan_trigger_failed", "error",
                   {"mode": mode, "error": f"{type(exc).__name__}: {exc}"})
            s.commit()
        raise HTTPException(500, f"could not start scan: {exc}") from exc

    background.add_task(
        run_pending_scan,
        run_id=pending["run_id"], correlation_id=pending["correlation_id"],
        mode=mode, triggered_by=identity["username"], n_targets=n_targets,
    )
    return _jsonable({**pending, "targets": n_targets})


@app.get("/api/scans/{run_id}")
def scan_status(run_id: str, identity=Depends(require_session)) -> dict:
    """Status of one run. Lets a caller poll a scan started with 202.

    `controls_evaluated` / `total_controls` give a real progress fraction during the
    evaluation phase -- distinct control_id count is genuinely incremental now that
    run_pending_scan commits per control rather than in one batch at the end.

    `targets_collected` / `total_targets` cover the *other* phase, which dominates
    wall-clock time for anything beyond one target (Phase 8: 128s of sequential SSH
    for 50 targets, almost all of it before a single result row exists). Every
    collector credential lookup writes a `credential_used` audit_log row carrying
    run_id (Section 6) and is committed per-target already -- so counting those rows
    is a real, already-existing signal, not a new one built just to animate a bar.
    `total_targets` comes from the `scan_started` event's own recorded detail.
    """
    from control_library import load_controls

    with get_engine().connect() as conn:
        row = conn.execute(text(
            "SELECT run_id, status, triggered_by, started_at, completed_at "
            "FROM runs WHERE run_id = :r"), {"r": run_id}).mappings().first()
        if row is None:
            raise HTTPException(404, f"no such run: {run_id}")
        n = conn.execute(text(
            "SELECT count(*) FROM results WHERE run_id = :r"), {"r": run_id}).scalar()
        controls_evaluated = conn.execute(text(
            "SELECT count(DISTINCT control_id) FROM results WHERE run_id = :r"),
            {"r": run_id}).scalar()
        targets_collected = conn.execute(text(
            "SELECT count(*) FROM audit_log "
            "WHERE run_id = :r AND event_type = 'credential_used'"),
            {"r": run_id}).scalar()
        total_targets = conn.execute(text(
            "SELECT (details->>'targets')::int FROM audit_log "
            "WHERE run_id = :r AND event_type = 'scan_started' LIMIT 1"),
            {"r": run_id}).scalar()
    return _jsonable({
        **dict(row), "results": n,
        "controls_evaluated": controls_evaluated,
        "total_controls": len(load_controls()),
        "targets_collected": targets_collected,
        "total_targets": total_targets or 1,
    })


@app.post("/api/exceptions")
def request_exception_endpoint(body: dict = Body(...),
                               identity=Depends(require_session)) -> dict:
    """Request an exception. STATE-CHANGING -- requires a session, and is audited."""
    from audit import AuditSink
    from exceptions_service import ExceptionWorkflowError, request_exception

    required = ("control_id", "resource_id", "justification", "expiry_date")
    missing = [k for k in required if not body.get(k)]
    if missing:
        raise HTTPException(400, f"missing required field(s): {missing}")

    try:
        expiry = datetime.datetime.fromisoformat(str(body["expiry_date"]))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=datetime.timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, f"expiry_date is not ISO-8601: {exc}") from exc

    with _sessionmaker()() as s:
        sink = AuditSink(s, uuid.uuid4(), None, actor=identity["username"])
        try:
            exception_id = request_exception(
                s, body["control_id"], body["resource_id"],
                # The requester is the AUTHENTICATED user, never a value from the
                # request body. Otherwise separation of duties is trivially defeated
                # by claiming to be someone else.
                requested_by=identity["username"],
                justification=body["justification"],
                expiry_date=expiry,
                compensating_control=body.get("compensating_control"),
                audit_sink=sink,
            )
        except ExceptionWorkflowError as exc:
            s.commit()
            raise HTTPException(400, str(exc)) from exc
        s.commit()
    return {"exception_id": str(exception_id), "status": "pending_review"}


@app.post("/api/exceptions/{exception_id}/approve")
def approve_exception_endpoint(exception_id: str, body: dict = Body(default={}),
                               identity=Depends(require_session)) -> dict:
    """Approve an exception. STATE-CHANGING -- requires a session, and is audited.

    The approver is the authenticated user. Separation of duties for high/critical
    severity is enforced in exceptions_service and surfaces here as HTTP 403.
    """
    from audit import AuditSink
    from exceptions_service import ApprovalError, approve_exception

    with _sessionmaker()() as s:
        sink = AuditSink(s, uuid.uuid4(), None, actor=identity["username"])
        try:
            approve_exception(
                s, uuid.UUID(exception_id),
                approved_by=identity["username"],
                status=str(body.get("status", "accepted_risk")),
                audit_sink=sink,
            )
        except ApprovalError as exc:
            s.commit()  # the denial audit row must persist
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, f"invalid exception_id: {exc}") from exc
        s.commit()
    return {"exception_id": exception_id, "approved_by": identity["username"]}


@app.get("/api/reports/pdf")
def report_pdf(run_id: str | None = Query(default=None),
               identity=Depends(require_session)):
    """Export the run as a PDF. Requires a session, and writes a report_exported row.

    Export is audited because a compliance report is a disclosure event: it packages
    every failing control, its evidence and its resource into one portable file. Who
    took a copy, and when, is exactly what an investigator needs afterwards.
    """
    from reports.generator import build_report

    with get_engine().connect() as conn:
        run = _resolve_run(conn, run_id)
        pdf_bytes = build_report(conn, run)
        # Reuse the RUN's correlation_id rather than minting a new one. Spec Section 7
        # requires a shared correlation_id per run, and an export tagged with a run_id
        # but a fresh correlation_id would sit outside that run's trail -- an
        # investigator following the correlation_id would never see that a report of
        # this run was taken.
        run_correlation = conn.execute(
            text("SELECT correlation_id FROM runs WHERE run_id = :r"), {"r": run}
        ).scalar()

    with _sessionmaker()() as s:
        _audit(s, identity["username"], "report_exported", "ok",
               {"run_id": str(run), "format": "pdf", "bytes": len(pdf_bytes)},
               correlation_id=run_correlation, run_id=run)
        s.commit()

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="audit-report-{run}.pdf"'},
    )
