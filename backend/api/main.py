"""
FastAPI application serving the dashboard and report export.

Every endpoint is read-only and derives its numbers from the append-only `results`
table via `backend/queries.py`. There is no summary table, no cached rollup and no
figure computed in the frontend — the dashboard renders what the database says, so a
number on screen can always be reproduced with a direct SQL query. The Phase 6
verification harness does exactly that for every figure.

Auth: spec Section 1 says session-based auth is sufficient for the MVP and Section 8
rules out SSO/OAuth. No auth is implemented here yet — Phase 6's acceptance criteria
concern the dashboard and export only. Flagged in BUILD_LOG as an open item; this API
must not be exposed beyond localhost until it exists.
"""

from __future__ import annotations

import datetime
import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from db import get_engine  # noqa: E402
from queries import (  # noqa: E402
    classify_drift,
    compliance_trend,
    dashboard_summary,
    drift_between,
    findings_for_report,
    latest_completed_run,
    open_exceptions,
    per_domain_breakdown,
    severity_breakdown,
)

app = FastAPI(
    title="Automated IT Systems Audit Tool",
    description="Read-only dashboard and report API over append-only audit evidence.",
    version="0.6.0",
)

# The Next.js dev server runs on a different port. Restricted to localhost origins;
# this API has no auth yet and must not be reachable from anywhere else.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _provider(control_id: str) -> str:
    """Which collector produced a control's findings.

    Used to label AWS findings in the UI and PDF. Phase 5 is verified against moto
    rather than a real account, so AWS findings carry a caveat that Linux findings do
    not — presenting them side by side as equally evidenced would misrepresent both.
    """
    return "aws" if control_id.startswith("AWS-") else "linux"


def _resolve_run(conn, run_id: str | None):
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
    if hasattr(value, "quantize"):  # Decimal
        return float(value)
    if hasattr(value, "hex") and hasattr(value, "int"):  # UUID
        return str(value)
    return value


@app.get("/api/health")
def health() -> dict:
    with get_engine().connect() as conn:
        run = latest_completed_run(conn)
    return {"status": "ok", "latest_completed_run": str(run) if run else None}


@app.get("/api/dashboard")
def dashboard(run_id: str | None = Query(default=None)) -> dict:
    """Everything the dashboard needs, in one round trip."""
    with get_engine().connect() as conn:
        run = _resolve_run(conn, run_id)
        summary = dashboard_summary(conn, run)
        domains = per_domain_breakdown(conn, run)
        severities = severity_breakdown(conn, run)
        exceptions = open_exceptions(conn)
        trend = compliance_trend(conn)

        drift = []
        if len(trend) >= 2:
            rows = drift_between(conn, trend[-2]["run_id"], trend[-1]["run_id"])
            buckets = classify_drift(rows)
            drift = [
                {"kind": kind, **_jsonable(row)}
                for kind, rows_ in buckets.items()
                for row in rows_
            ]

    return _jsonable(
        {
            "run_id": str(run),
            "generated_at": datetime.datetime.now(datetime.timezone.utc),
            "summary": summary,
            "per_domain": domains,
            "open_findings_by_severity": severities,
            "exceptions": exceptions,
            "trend": trend,
            "drift_since_previous_run": drift,
        }
    )


@app.get("/api/findings")
def findings(run_id: str | None = Query(default=None)) -> dict:
    with get_engine().connect() as conn:
        run = _resolve_run(conn, run_id)
        rows = findings_for_report(conn, run)

    return _jsonable(
        {
            "run_id": str(run),
            "findings": [{**r, "provider": _provider(r["control_id"])} for r in rows],
        }
    )


@app.get("/api/reports/pdf")
def report_pdf(run_id: str | None = Query(default=None)):
    """Export the run as a framework-mapped PDF with per-finding evidence."""
    from reports.generator import build_report

    with get_engine().connect() as conn:
        run = _resolve_run(conn, run_id)
        pdf_bytes = build_report(conn, run)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="audit-report-{run}.pdf"'
        },
    )
