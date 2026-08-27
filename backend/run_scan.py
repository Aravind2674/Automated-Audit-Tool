"""
Phase 2 scan orchestrator: collect -> normalize -> evaluate -> persist.

Writes one `runs` row per scan and one `results` row per control/resource pair, plus
audit_log rows sharing a single correlation_id for the whole run.

Usage:
    python backend/run_scan.py --from-vagrant-ssh-config
    python backend/run_scan.py --raw phase1_raw_output.json     # re-evaluate cached
    python backend/run_scan.py --raw phase1_raw_output.json --no-db
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from audit import AuditSink, NullAuditSink  # noqa: E402
from collectors.ssh_collector import SSHCollector  # noqa: E402
from control_library import load_controls, required_sources  # noqa: E402
from engine.evaluator import evaluate  # noqa: E402
from engine.normalizer import normalize  # noqa: E402
from phase1_collect import target_from_vagrant_ssh_config  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).parent.parent


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def persist_controls(session, controls: list[dict]) -> None:
    """Load the YAML control library into the controls table (spec Section 3)."""
    from models.schema import Control

    for control in controls:
        existing = session.get(Control, control["id"])
        if existing is None:
            session.add(
                Control(
                    id=control["id"],
                    title=control["title"],
                    description=control["description"],
                    category=control["category"],
                    severity=control["severity"],
                    applies_to=control["applies_to"],
                    scored=control["scored"],
                    framework_mappings=control["framework_mappings"],
                    test_logic=control["test_logic"],
                    remediation=control["remediation"],
                )
            )
        else:
            # controls is a definition table, not an append-only evidence table --
            # refreshing it from YAML at startup is what the spec calls for.
            existing.title = control["title"]
            existing.description = control["description"]
            existing.category = control["category"]
            existing.severity = control["severity"]
            existing.applies_to = control["applies_to"]
            existing.scored = control["scored"]
            existing.framework_mappings = control["framework_mappings"]
            existing.test_logic = control["test_logic"]
            existing.remediation = control["remediation"]


def execute_scan(mode: str = "cached", triggered_by: str = "api",
                 raw_path: str | None = None) -> dict:
    """Run a scan and persist it. Used by the API's POST /api/scans endpoint.

    mode="cached"  re-evaluate the stored raw collection (fast, deterministic)
    mode="live"    collect from the demo VM over SSH first, with credentials
                   resolved through secrets_manager

    Returns a summary dict. Every path writes a `runs` row, per-control `results`
    rows and the audit trail, all sharing one correlation_id.
    """
    from audit import AuditSink
    from db import create_schema, get_engine, get_sessionmaker
    from models.schema import Result, Run

    controls = load_controls()
    run_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    started_at = _now()

    engine = get_engine()
    create_schema(engine)
    session = get_sessionmaker(engine)()

    try:
        sink = AuditSink(session, correlation_id, run_id, actor=triggered_by)
        persist_controls(session, controls)
        session.add(Run(
            run_id=run_id, correlation_id=correlation_id, triggered_by=triggered_by,
            started_at=started_at, completed_at=None, status="running",
        ))
        session.commit()

        sink.event("scan_started", "ok", {"mode": mode, "controls": len(controls)})
        session.commit()

        if mode == "live":
            target = target_from_vagrant_ssh_config()
            # Only the sources required by controls that actually APPLY to a Linux
            # host. required_sources(controls) would include the AWS sources added in
            # Phase 5, which the SSH collector has no command mapping for -- a latent
            # break in the live-scan path that the cached path never exercises,
            # because it skips collection entirely.
            target["sources"] = required_sources(
                [c for c in controls if "linux_server" in c["applies_to"]]
            )
            # Credentials come from secrets_manager because db_session is passed.
            collector = SSHCollector(
                db_session=session, actor=triggered_by,
                correlation_id=correlation_id, run_id=run_id,
            )
            raw_docs = collector.collect(target)
            collector_type = collector.collector_type
        else:
            path = pathlib.Path(raw_path or (REPO_ROOT / "phase1_raw_output.json"))
            raw_docs = json.loads(path.read_text(encoding="utf-8"))
            collector_type = raw_docs[0]["collector_type"]

        resources = normalize(raw_docs, collector_type)

        all_results = []
        for control in controls:
            all_results.extend(evaluate(
                control, resources, audit_sink=sink,
                correlation_id=str(correlation_id), run_id=str(run_id),
                actor=triggered_by,
            ))

        evaluated_at = _now()
        for result in all_results:
            session.add(Result(
                result_id=uuid.uuid4(), run_id=run_id,
                control_id=result["control_id"], resource_id=result["resource_id"],
                outcome=result["outcome"], evidence=result["evidence"],
                evaluated_at=evaluated_at,
            ))

        run = session.get(Run, run_id)
        run.completed_at = _now()
        run.status = "completed"
        sink.event("scan_completed", "ok", {"results": len(all_results)})
        session.commit()

        counts: dict[str, int] = {}
        for r in all_results:
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        scored = counts.get("pass", 0) + counts.get("fail", 0)

        return {
            "run_id": str(run_id),
            "correlation_id": str(correlation_id),
            "mode": mode,
            "triggered_by": triggered_by,
            "results": len(all_results),
            "outcomes": counts,
            "compliance_pct": round(100.0 * counts.get("pass", 0) / scored, 1)
            if scored else None,
        }
    except Exception:
        session.rollback()
        run = session.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.completed_at = _now()
            session.commit()
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-vagrant-ssh-config", action="store_true")
    parser.add_argument("--raw", help="re-evaluate a cached raw collection JSON")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="vagrant")
    parser.add_argument("--key", dest="key_filename")
    parser.add_argument("--triggered-by", default="cli")
    parser.add_argument("--no-db", action="store_true", help="evaluate without persisting")
    parser.add_argument(
        "--controls-dir",
        help="load controls from this directory instead of backend/controls/. "
             "Used to exercise drift across a CHANGED control set without "
             "mutating the real 18-control library.",
    )
    args = parser.parse_args()

    controls = load_controls(
        pathlib.Path(args.controls_dir) if args.controls_dir else None
    )
    run_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    started_at = _now()

    # ---- collect -----------------------------------------------------------
    if args.raw:
        raw_docs = json.loads(pathlib.Path(args.raw).read_text(encoding="utf-8"))
        collector_type = raw_docs[0]["collector_type"]
    else:
        if args.from_vagrant_ssh_config:
            target = target_from_vagrant_ssh_config()
        elif args.host:
            target = {
                "target_id": "demo-ubuntu-vagrant", "host": args.host,
                "port": args.port, "user": args.user,
                "key_filename": args.key_filename,
            }
        else:
            parser.error("supply --raw, --from-vagrant-ssh-config, or --host")
        # Only the sources required by controls that actually APPLY to a Linux host.
        # required_sources(controls) would include the AWS sources added in Phase 5,
        # which the SSH collector has no command mapping for -- a latent break in the
        # live-scan path that the cached path never exercises because it skips
        # collection entirely.
        target["sources"] = required_sources(
            [c for c in controls if "linux_server" in c["applies_to"]]
        )
        collector = SSHCollector()
        raw_docs = collector.collect(target)
        collector_type = collector.collector_type

    # ---- normalize ---------------------------------------------------------
    resources = normalize(raw_docs, collector_type)

    # ---- persistence setup -------------------------------------------------
    session = None
    if args.no_db:
        sink = NullAuditSink()
    else:
        from db import create_schema, get_engine, get_sessionmaker
        from models.schema import Result, Run

        engine = get_engine()
        create_schema(engine)
        session = get_sessionmaker(engine)()
        sink = AuditSink(session, correlation_id, run_id, actor=args.triggered_by)

        persist_controls(session, controls)
        session.add(
            Run(
                run_id=run_id, correlation_id=correlation_id,
                triggered_by=args.triggered_by, started_at=started_at,
                completed_at=None, status="running",
            )
        )
        session.commit()

    sink.event("scan_started", "ok", {"controls": len(controls), "resources": len(resources)})

    # ---- evaluate ----------------------------------------------------------
    all_results: list[dict] = []
    for control in controls:
        all_results.extend(
            evaluate(
                control, resources, audit_sink=sink,
                correlation_id=str(correlation_id), run_id=str(run_id),
                actor=args.triggered_by,
            )
        )

    # ---- persist results (INSERT only) -------------------------------------
    if session is not None:
        from models.schema import Result, Run

        evaluated_at = _now()
        for result in all_results:
            session.add(
                Result(
                    result_id=uuid.uuid4(), run_id=run_id,
                    control_id=result["control_id"], resource_id=result["resource_id"],
                    outcome=result["outcome"], evidence=result["evidence"],
                    evaluated_at=evaluated_at,
                )
            )
        run = session.get(Run, run_id)
        run.completed_at = _now()
        run.status = "completed"

    # Emitted regardless of persistence mode: the audit trail must record that the
    # scan finished even when the run is not being written to a database.
    sink.event("scan_completed", "ok", {"results": len(all_results)})

    if session is not None:
        session.commit()
        session.close()

    # ---- report ------------------------------------------------------------
    counts: dict[str, int] = {}
    for result in all_results:
        counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
    scored_total = sum(counts.get(k, 0) for k in ("pass", "fail"))

    print(f"run_id         : {run_id}")
    print(f"correlation_id : {correlation_id}")
    print(f"resources      : {len(resources)}")
    print(f"results        : {len(all_results)}")
    print(f"outcomes       : {counts}")
    if scored_total:
        print(f"compliance     : {counts.get('pass', 0)}/{scored_total} = "
              f"{100 * counts.get('pass', 0) / scored_total:.1f}%")
    if args.no_db:
        print(f"audit rows     : {len(sink.rows)} (in memory, --no-db)")
    else:
        print("persisted      : runs + results + audit_log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
