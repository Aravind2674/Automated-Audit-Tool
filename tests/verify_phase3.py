"""
Phase 3 verification: historical results are immutable, and the trend query is correct.

Proves the append-only guarantee empirically rather than by asserting it. Before a new
scan, every existing `results` and `audit_log` row is fingerprinted column-by-column.
After the scan, the rows that existed beforehand are fingerprinted again and the two
digests are compared.

Why a per-row digest rather than a row count: a count catches deletions but not
mutations. If a later run silently rewrote a prior finding's `outcome` or `evidence` --
the exact failure this project's append-only rule exists to prevent -- the count would
be unchanged and the digest would not.

Usage:
    python tests/verify_phase3.py --snapshot-before   # capture, then run a scan
    python tests/verify_phase3.py --verify-after      # compare against the capture
    python tests/verify_phase3.py --trend             # print + validate the trend query
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from db import get_engine  # noqa: E402
from queries import classify_drift, compliance_trend, drift_between  # noqa: E402

SNAPSHOT_PATH = (
    pathlib.Path(__file__).parent / ".phase3_snapshot.json"
)

RESULTS_SQL = """
SELECT result_id, run_id, control_id, resource_id, outcome,
       evidence::text AS evidence, evaluated_at::text AS evaluated_at
FROM results ORDER BY result_id
"""

AUDIT_SQL = """
SELECT event_id, correlation_id, run_id, actor, event_type,
       timestamp::text AS timestamp, result, details::text AS details
FROM audit_log ORDER BY event_id
"""

RUNS_SQL = """
SELECT run_id, correlation_id, triggered_by, started_at::text AS started_at,
       completed_at::text AS completed_at, status
FROM runs ORDER BY run_id
"""


def _digest(row: dict) -> str:
    payload = json.dumps({k: str(v) for k, v in sorted(row.items())}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _fingerprint(conn) -> dict:
    out = {}
    for table, sql, key in (
        ("results", RESULTS_SQL, "result_id"),
        ("audit_log", AUDIT_SQL, "event_id"),
        ("runs", RUNS_SQL, "run_id"),
    ):
        rows = [dict(r) for r in conn.execute(text(sql)).mappings()]
        out[table] = {str(r[key]): _digest(r) for r in rows}
    return out


def snapshot_before() -> int:
    with get_engine().connect() as conn:
        fingerprint = _fingerprint(conn)
    SNAPSHOT_PATH.write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")
    print("Snapshot captured (per-row SHA-256 of every column):")
    for table, rows in fingerprint.items():
        print(f"  {table:<10} {len(rows)} rows fingerprinted")
    print(f"\nwritten to {SNAPSHOT_PATH.name}")
    return 0


def verify_after() -> int:
    if not SNAPSHOT_PATH.exists():
        print("ERROR: no snapshot found -- run --snapshot-before first")
        return 2

    before = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    with get_engine().connect() as conn:
        after = _fingerprint(conn)

    failures: list[str] = []
    print("Immutability check: rows that existed before the new scan\n")
    print(f"{'TABLE':<10} {'BEFORE':>7} {'AFTER':>7} {'NEW':>5} {'MUTATED':>8} {'DELETED':>8}")
    print("-" * 52)

    for table in ("results", "audit_log", "runs"):
        old, new = before[table], after[table]
        deleted = [k for k in old if k not in new]
        mutated = [k for k in old if k in new and old[k] != new[k]]
        added = [k for k in new if k not in old]

        print(f"{table:<10} {len(old):>7} {len(new):>7} {len(added):>5} "
              f"{len(mutated):>8} {len(deleted):>8}")

        # runs IS allowed to change: completed_at/status are set when a scan
        # finishes. results and audit_log are not.
        if table in ("results", "audit_log"):
            if mutated:
                failures.append(f"{table}: {len(mutated)} pre-existing row(s) MUTATED: {mutated[:5]}")
            if deleted:
                failures.append(f"{table}: {len(deleted)} pre-existing row(s) DELETED: {deleted[:5]}")
        else:
            # For runs, only rows already 'completed' must stay frozen.
            frozen_violations = [k for k in mutated]
            if frozen_violations:
                failures.append(
                    f"runs: {len(frozen_violations)} prior run row(s) changed "
                    f"(acceptable only if they were still 'running'): {frozen_violations[:5]}"
                )
            if deleted:
                failures.append(f"runs: {len(deleted)} row(s) DELETED: {deleted[:5]}")

    print()
    if failures:
        print("*** APPEND-ONLY VIOLATION ***")
        for f in failures:
            print(f"  {f}")
        return 1

    print("PASS: no pre-existing results or audit_log row was mutated or deleted.")
    return 0


def _validate_trend(conn, trend: list[dict]) -> list[str]:
    """Recompute compliance % independently and compare to the query's answer."""
    problems = []
    for row in trend:
        raw = conn.execute(
            text("SELECT outcome, count(*) c FROM results WHERE run_id = :r GROUP BY outcome"),
            {"r": row["run_id"]},
        ).mappings().all()
        counts = {x["outcome"]: x["c"] for x in raw}
        passed = counts.get("pass", 0)
        failed = counts.get("fail", 0)
        scored = passed + failed
        expected = round(100.0 * passed / scored, 1) if scored else None

        if int(row["passed"]) != passed:
            problems.append(f"{row['run_id']}: passed {row['passed']} != {passed}")
        if int(row["failed"]) != failed:
            problems.append(f"{row['run_id']}: failed {row['failed']} != {failed}")
        if expected is not None and abs(float(row["compliance_pct"]) - expected) > 0.05:
            problems.append(
                f"{row['run_id']}: compliance {row['compliance_pct']} != {expected}"
            )
    return problems


def show_trend() -> int:
    with get_engine().connect() as conn:
        trend = compliance_trend(conn)

        print("Compliance trend (one row per completed run, oldest first)\n")
        print(f"{'#':<3} {'RUN_ID':<38} {'COMPLETED':<22} {'PASS':>5} {'FAIL':>5} "
              f"{'ERR':>4} {'MR':>3} {'COMPLIANCE':>11}")
        print("-" * 96)
        for i, row in enumerate(trend, 1):
            print(f"{i:<3} {str(row['run_id']):<38} {str(row['completed_at'])[:19]:<22} "
                  f"{row['passed']:>5} {row['failed']:>5} {row['errored']:>4} "
                  f"{row['manual_review']:>3} {str(row['compliance_pct']) + '%':>11}")

        print()
        problems = _validate_trend(conn, trend)
        if problems:
            print("*** TREND QUERY INCORRECT ***")
            for p in problems:
                print(f"  {p}")
            return 1
        print(f"PASS: all {len(trend)} trend rows independently recomputed and matched.")

        if len(trend) >= 2:
            print("\nDrift between consecutive runs:")
            for prev, curr in zip(trend, trend[1:]):
                rows = drift_between(conn, prev["run_id"], curr["run_id"])
                buckets = classify_drift(rows)
                summary = ", ".join(
                    f"{len(v)} {k}" for k, v in buckets.items() if v
                ) or "no change"
                print(f"  run {str(prev['run_id'])[:8]} -> {str(curr['run_id'])[:8]}: {summary}")
                for kind in ("improved", "regressed", "appeared", "disappeared", "other"):
                    for r in buckets[kind]:
                        print(f"      {kind:<12} {r['control_id']:<12} [{r['severity']}] "
                              f"{r['previous_outcome']} -> {r['current_outcome']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-before", action="store_true")
    parser.add_argument("--verify-after", action="store_true")
    parser.add_argument("--trend", action="store_true")
    args = parser.parse_args()

    if args.snapshot_before:
        return snapshot_before()
    if args.verify_after:
        return verify_after()
    if args.trend:
        return show_trend()
    parser.error("choose --snapshot-before, --verify-after or --trend")


if __name__ == "__main__":
    sys.exit(main())
