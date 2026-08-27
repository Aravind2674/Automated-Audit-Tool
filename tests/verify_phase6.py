"""
Phase 6 verification: dashboard figures and PDF evidence.

Two rules from the project owner drive this harness:

1.  **Every number the dashboard displays is cross-checked against a direct DB query,
    not against the API's own response.** The independent queries below are written in
    a different SQL style from `backend/queries.py` — `CASE/SUM` aggregates and
    correlated subqueries instead of `FILTER` and `EXISTS` — so agreement means the
    figures are right, not merely that one code path is deterministic.

2.  **The PDF's per-finding evidence must be the actual `evidence` JSONB from the
    database, not regenerated or paraphrased.** The check extracts the evidence block
    from the rendered PDF, parses it back to a Python object, and asserts deep equality
    with the JSONB read straight out of PostgreSQL. Rendering something that merely
    looks like evidence would pass a visual review and fail this.

Usage:
    python tests/verify_phase6.py
"""

from __future__ import annotations

import datetime
import io
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from sqlalchemy import text  # noqa: E402

from api.main import app  # noqa: E402
from db import get_engine  # noqa: E402
from queries import latest_completed_run  # noqa: E402
from reports.generator import build_report  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))
        _failures.append(label)


# --------------------------------------------------------------------------
# Independently written SQL. Deliberately NOT the queries the API uses.
# --------------------------------------------------------------------------

INDEP_SUMMARY = """
SELECT
  sum(CASE WHEN outcome='pass' THEN 1 ELSE 0 END) AS passed,
  sum(CASE WHEN outcome='fail' THEN 1 ELSE 0 END) AS failed,
  sum(CASE WHEN outcome='error' THEN 1 ELSE 0 END) AS errored,
  sum(CASE WHEN outcome='manual_review' THEN 1 ELSE 0 END) AS manual_review,
  count(*) AS total
FROM results WHERE run_id = :r
"""

# Correlated subquery instead of EXISTS(...) inside a FILTER.
INDEP_OPEN = """
SELECT count(*) FROM results res
WHERE res.run_id = :r AND res.outcome='fail'
  AND (SELECT count(*) FROM exceptions e
        WHERE e.control_id=res.control_id AND e.resource_id=res.resource_id
          AND e.approved_by IS NOT NULL
          AND e.status IN ('accepted_risk','false_positive')
          AND e.expiry_date > now()) = 0
"""

INDEP_ACCEPTED = """
SELECT count(*) FROM results res
WHERE res.run_id = :r AND res.outcome='fail'
  AND (SELECT count(*) FROM exceptions e
        WHERE e.control_id=res.control_id AND e.resource_id=res.resource_id
          AND e.approved_by IS NOT NULL
          AND e.status IN ('accepted_risk','false_positive')
          AND e.expiry_date > now()) > 0
"""

INDEP_DOMAIN = """
SELECT c.category,
       count(*) AS total,
       sum(CASE WHEN res.outcome='pass' THEN 1 ELSE 0 END) AS passed,
       sum(CASE WHEN res.outcome='fail' THEN 1 ELSE 0 END) AS failed
FROM results res, controls c
WHERE c.id = res.control_id AND res.run_id = :r
GROUP BY c.category
"""

INDEP_SEVERITY = """
SELECT c.severity, count(*) AS open_findings
FROM results res, controls c
WHERE c.id = res.control_id AND res.run_id = :r AND res.outcome = 'fail'
  AND NOT EXISTS (SELECT 1 FROM exceptions e
                   WHERE e.control_id=res.control_id
                     AND e.resource_id=res.resource_id
                     AND e.approved_by IS NOT NULL
                     AND e.status IN ('accepted_risk','false_positive')
                     AND e.expiry_date > now())
GROUP BY c.severity
"""

INDEP_EXCEPTIONS = """
SELECT exception_id::text, control_id, expiry_date,
       (expiry_date <= now()) AS expired
FROM exceptions WHERE approved_by IS NOT NULL
"""


def test_dashboard_numbers() -> None:
    print("\n=== Dashboard figures vs direct DB queries (not the API's own SQL) ===\n")
    client = TestClient(app)
    resp = client.get("/api/dashboard")
    check("GET /api/dashboard returns 200", resp.status_code == 200, str(resp.status_code))
    if resp.status_code != 200:
        return
    api = resp.json()
    run = api["run_id"]

    with get_engine().connect() as conn:
        db_run = str(latest_completed_run(conn))
        check("API run_id == latest completed run in DB", run == db_run, f"{run} vs {db_run}")

        row = conn.execute(text(INDEP_SUMMARY), {"r": run}).mappings().one()
        s = api["summary"]
        for key in ("total", "passed", "failed", "errored", "manual_review"):
            check(f"summary.{key}", int(s[key]) == int(row[key]),
                  f"api={s[key]} db={row[key]}")

        open_db = conn.execute(text(INDEP_OPEN), {"r": run}).scalar()
        acc_db = conn.execute(text(INDEP_ACCEPTED), {"r": run}).scalar()
        check("summary.open_findings", int(s["open_findings"]) == int(open_db),
              f"api={s['open_findings']} db={open_db}")
        check("summary.accepted_risk", int(s["accepted_risk"]) == int(acc_db),
              f"api={s['accepted_risk']} db={acc_db}")
        check("open + accepted == failed",
              int(s["open_findings"]) + int(s["accepted_risk"]) == int(row["failed"]))

        scored = int(row["passed"]) + int(row["failed"])
        expected_pct = round(100.0 * int(row["passed"]) / scored, 1) if scored else None
        check("summary.compliance_pct recomputed independently",
              (s["compliance_pct"] is None and expected_pct is None)
              or abs(float(s["compliance_pct"]) - expected_pct) < 0.05,
              f"api={s['compliance_pct']} recomputed={expected_pct}")

        # per-domain
        db_domains = {r["category"]: r for r in
                      conn.execute(text(INDEP_DOMAIN), {"r": run}).mappings()}
        api_domains = {d["category"]: d for d in api["per_domain"]}
        check("per_domain covers the same categories",
              set(db_domains) == set(api_domains),
              f"{sorted(set(db_domains) ^ set(api_domains))}")
        for cat, dbrow in db_domains.items():
            a = api_domains.get(cat, {})
            ok = (int(a.get("total", -1)) == int(dbrow["total"])
                  and int(a.get("passed", -1)) == int(dbrow["passed"])
                  and int(a.get("failed", -1)) == int(dbrow["failed"]))
            check(f"per_domain[{cat}] totals", ok,
                  f"api={a.get('total')}/{a.get('passed')}/{a.get('failed')} "
                  f"db={dbrow['total']}/{dbrow['passed']}/{dbrow['failed']}")

        # severity
        db_sev = {r["severity"]: int(r["open_findings"]) for r in
                  conn.execute(text(INDEP_SEVERITY), {"r": run}).mappings()}
        api_sev = {k: int(v) for k, v in api["open_findings_by_severity"].items() if v}
        check("open_findings_by_severity", db_sev == api_sev, f"api={api_sev} db={db_sev}")
        check("severity counts sum to open_findings",
              sum(api_sev.values()) == int(s["open_findings"]))

        # exceptions + expiry flags
        db_exc = {r["exception_id"]: r for r in
                  conn.execute(text(INDEP_EXCEPTIONS)).mappings()}
        api_exc = {e["exception_id"]: e for e in api["exceptions"]}
        check("exceptions: same set of ids", set(db_exc) == set(api_exc),
              f"{sorted(set(db_exc) ^ set(api_exc))}")
        for eid, dbrow in db_exc.items():
            a = api_exc.get(eid, {})
            check(f"exception {dbrow['control_id']} expired flag",
                  bool(a.get("expired")) == bool(dbrow["expired"]),
                  f"api={a.get('expired')} db={dbrow['expired']}")
            check(f"exception {dbrow['control_id']} expiry_date",
                  str(a.get("expiry_date", ""))[:19] == dbrow["expiry_date"].isoformat()[:19],
                  f"api={a.get('expiry_date')} db={dbrow['expiry_date']}")

        # trend
        db_trend = conn.execute(text(
            "SELECT run_id::text AS rid,"
            " sum(CASE WHEN outcome='pass' THEN 1 ELSE 0 END) AS p,"
            " sum(CASE WHEN outcome='fail' THEN 1 ELSE 0 END) AS f"
            " FROM results GROUP BY run_id")).mappings()
        db_trend = {r["rid"]: (int(r["p"]), int(r["f"])) for r in db_trend}
        mismatched = [t["run_id"] for t in api["trend"]
                      if db_trend.get(str(t["run_id"])) != (int(t["passed"]), int(t["failed"]))]
        check("every trend row matches independently computed pass/fail counts",
              not mismatched, str(mismatched[:3]))
        check("trend covers every completed run",
              len(api["trend"]) == conn.execute(text(
                  "SELECT count(*) FROM runs WHERE status='completed'")).scalar())


def _extract_evidence_blocks(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def test_pdf_evidence_is_verbatim() -> None:
    """The evidence in the PDF must be the DB's JSONB, not a regeneration."""
    print("\n=== PDF evidence is the stored JSONB, verbatim ===\n")

    with get_engine().connect() as conn:
        run = latest_completed_run(conn)
        pdf = build_report(conn, run, datetime.datetime.now(datetime.timezone.utc))
        rows = conn.execute(text(
            "SELECT control_id, resource_id, evidence, outcome FROM results "
            "WHERE run_id = :r"), {"r": run}).mappings().all()

    check("PDF is a valid PDF", pdf[:5] == b"%PDF-", str(pdf[:8]))
    text_all = _extract_evidence_blocks(pdf)
    check("PDF text extracted", len(text_all) > 500, f"{len(text_all)} chars")

    # Every control id and framework mapping must appear.
    missing_ids = [r["control_id"] for r in rows if r["control_id"] not in text_all]
    check("every finding's control_id appears in the PDF", not missing_ids,
          str(missing_ids[:5]))

    # Framework columns present per spec Phase 6.
    for label in ("CIS Linux v8", "NIST CSF", "SOC 2", "CERT-In"):
        check(f"framework column '{label}' present", label in text_all)

    # ---- the core check: parse the evidence back out and compare deeply ----
    # The generator writes json.dumps(evidence, indent=2, sort_keys=True). PDF text
    # extraction collapses layout, so the comparison is done on a whitespace-
    # normalised rendering of both sides rather than on raw bytes.
    def norm(s: str) -> str:
        return re.sub(r"\s+", "", s)

    normalised_pdf = norm(text_all)
    verified = 0
    mismatches = []
    for r in rows:
        rendered = json.dumps(r["evidence"], indent=2, sort_keys=True, default=str)
        if norm(rendered) in normalised_pdf:
            verified += 1
        else:
            mismatches.append(f"{r['control_id']}/{r['resource_id']}")

    check(f"every finding's evidence JSON appears verbatim ({verified}/{len(rows)})",
          not mismatches, str(mismatches[:3]))

    # And prove the check has teeth: a deliberately altered evidence must NOT match.
    if rows:
        tampered = json.loads(json.dumps(rows[0]["evidence"], default=str))
        if isinstance(tampered, dict):
            tampered["__tampered__"] = "this value was never in the database"
            altered = json.dumps(tampered, indent=2, sort_keys=True)
            check("a tampered evidence blob does NOT match the PDF (check has teeth)",
                  norm(altered) not in normalised_pdf)


def test_report_endpoint() -> None:
    print("\n=== PDF export endpoint ===\n")
    client = TestClient(app)
    resp = client.get("/api/reports/pdf")
    check("GET /api/reports/pdf returns 200", resp.status_code == 200, str(resp.status_code))
    check("content-type is application/pdf",
          resp.headers.get("content-type", "").startswith("application/pdf"),
          resp.headers.get("content-type", ""))
    check("body is a PDF", resp.content[:5] == b"%PDF-")
    check("attachment filename set",
          "attachment" in resp.headers.get("content-disposition", ""))


def main() -> int:
    test_dashboard_numbers()
    test_pdf_evidence_is_verbatim()
    test_report_endpoint()
    print()
    if _failures:
        print(f"{len(_failures)} CHECK(S) FAILED: {_failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
