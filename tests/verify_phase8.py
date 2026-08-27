"""
Phase 8 scale validation (spec Section 7a).

The original problem statement's NFR requires handling "at least 50 simulated
hosts/resources without redesign". Every run before this used exactly one Linux
target, so the requirement had zero evidence either way.

Two halves, with different honesty caveats:

* **AWS** — 50+ genuinely distinct mocked resources via moto. Each is a real,
  separately-configured resource as far as the collector, normalizer and evaluator are
  concerned.

* **Linux** — 50 target entries pointing at the SAME demo VM, with distinct
  `target_id`s and therefore distinct `resource_id`s. Provisioning 50 real VMs is not
  practical on this hardware. **This validates orchestration, database writes and
  dashboard aggregation across 50 targets. It does NOT validate 50 independent real
  security postures** — it is one host underneath, so all 50 produce identical
  findings by construction. That distinction is stated here, in architecture.md and in
  BUILD_LOG, and must not be blurred.

Rule 8: the database is queried independently afterwards to confirm it actually holds
50x the rows, rather than trusting that the process exited without error.

Usage:
    python tests/verify_phase8.py              # both halves, 50 each
    python tests/verify_phase8.py --targets 5  # quick smoke run
    python tests/verify_phase8.py --aws-only
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from sqlalchemy import text  # noqa: E402

from db import get_engine  # noqa: E402
from phase1_collect import target_from_vagrant_ssh_config  # noqa: E402
from run_scan import execute_multi_target_scan  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))
        _failures.append(label)


def build_aws_at_scale(n_each: int) -> dict:
    """Create n_each buckets + security groups + volumes inside an active moto mock."""
    import boto3

    region = "us-east-1"
    s3 = boto3.client("s3", region_name=region)
    ec2 = boto3.client("ec2", region_name=region)

    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    expected = {"buckets": 0, "security_groups": 0, "volumes": 0}

    for i in range(n_each):
        name = f"scale-bucket-{i:03d}"
        s3.create_bucket(Bucket=name)
        # Alternate compliant / non-compliant so the scale run produces a MIX, not a
        # uniform block -- a run where every resource has the same outcome would not
        # exercise aggregation meaningfully.
        if i % 2 == 0:
            s3.put_public_access_block(
                Bucket=name,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True, "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
                },
            )
        expected["buckets"] += 1

        sg = ec2.create_security_group(
            GroupName=f"scale-sg-{i:03d}", Description="scale test", VpcId=vpc
        )["GroupId"]
        ec2.authorize_security_group_ingress(
            GroupId=sg,
            IpPermissions=[{
                "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0" if i % 3 == 0 else "10.0.0.0/8"}],
            }],
        )
        expected["security_groups"] += 1

        ec2.create_volume(AvailabilityZone=f"{region}a", Size=8,
                          Encrypted=(i % 2 == 1))
        expected["volumes"] += 1

    return expected


def run_aws_scale(n_each: int) -> dict:
    from moto import mock_aws

    from collectors.aws_collector import AWSCollector

    print(f"\n=== AWS scale: {n_each} buckets + {n_each} security groups + "
          f"{n_each} volumes ===\n")

    with mock_aws():
        expected = build_aws_at_scale(n_each)
        collect_start = time.perf_counter()
        raw_docs = AWSCollector().collect({"target_id": "scale-aws-account"})
        collect_s = round(time.perf_counter() - collect_start, 2)

    result = execute_multi_target_scan(
        targets=[{"target_id": "scale-aws-account"}],
        triggered_by="phase8-scale",
        collector_type="aws",
        aws_raw_docs=raw_docs,
    )
    result["timings"]["collect_s"] = collect_s
    result["expected_resources"] = expected

    print(f"  resources normalized : {result['resources']}")
    print(f"  results persisted    : {result['results']}")
    print(f"  outcomes             : {result['outcomes']}")
    print(f"  collect (moto)       : {collect_s}s")
    print(f"  evaluate             : {result['timings']['evaluate_s']}s")
    print(f"  persist              : {result['timings']['persist_s']}s")
    print(f"  TOTAL                : {result['timings']['total_s']}s")
    return result


def run_linux_scale(n_targets: int) -> dict:
    print(f"\n=== Linux scale: {n_targets} targets against the SAME demo VM ===")
    print("    (orchestration/DB/UI scale only -- NOT 50 independent real hosts)\n")

    base = target_from_vagrant_ssh_config()
    targets = []
    for i in range(n_targets):
        t = dict(base)
        # Distinct target_id -> distinct resource_id.
        t["target_id"] = base["target_id"] if i == 0 else f"{base['target_id']}-clone-{i:03d}"
        targets.append(t)

    # Every target needs its own credential entry. secrets_manager correctly refuses
    # to serve a credential for an unregistered target_id -- discovered by this
    # harness failing on the first clone, which is the store behaving as designed.
    # Registering one per target is exactly what onboarding 50 real hosts would
    # involve, and it exercises the credential store at scale as a side effect.
    from db import get_sessionmaker
    from secrets_manager import has_credential, store_credential

    key_material = pathlib.Path(base["key_filename"]).read_text(encoding="utf-8")
    Session = get_sessionmaker(get_engine())
    registered = 0
    with Session() as s:
        for t in targets:
            if not has_credential(s, t["target_id"]):
                store_credential(
                    s, t["target_id"], key_material,
                    credential_type="ssh_private_key",
                    description="Phase 8 scale target (same demo VM underneath)",
                )
                registered += 1
        s.commit()
    print(f"    registered {registered} new credential entries "
          f"({n_targets - registered} already present)\n")

    def progress(i, total, target_id):
        if i == 1 or i % 10 == 0 or i == total:
            print(f"    [{i:>3}/{total}] {target_id}")

    return execute_multi_target_scan(
        targets=targets, triggered_by="phase8-scale",
        collector_type="ssh", progress=progress,
    )


def verify_in_db(run_id: str, expect_results: int, expect_resources: int,
                 label: str) -> None:
    """Rule 8: confirm the database really holds the data, independently."""
    print(f"\n--- rule 8: independent DB verification ({label}) ---")
    with get_engine().connect() as conn:
        n_results = conn.execute(text(
            "SELECT count(*) FROM results WHERE run_id = :r"), {"r": run_id}).scalar()
        n_resources = conn.execute(text(
            "SELECT count(DISTINCT resource_id) FROM results WHERE run_id = :r"),
            {"r": run_id}).scalar()
        n_evidence = conn.execute(text(
            "SELECT count(*) FROM results WHERE run_id = :r "
            "AND evidence IS NOT NULL AND evidence::text <> '{}'"), {"r": run_id}).scalar()
        status = conn.execute(text(
            "SELECT status FROM runs WHERE run_id = :r"), {"r": run_id}).scalar()
        corr = conn.execute(text(
            "SELECT count(DISTINCT correlation_id) FROM audit_log WHERE run_id = :r"),
            {"r": run_id}).scalar()

    check(f"{label}: run status is completed", status == "completed", str(status))
    check(f"{label}: results rows in DB == {expect_results}",
          n_results == expect_results, f"db={n_results}")
    check(f"{label}: distinct resource_ids == {expect_resources}",
          n_resources == expect_resources, f"db={n_resources}")
    check(f"{label}: every result carries evidence",
          n_evidence == n_results, f"{n_evidence}/{n_results}")
    check(f"{label}: one correlation_id for the whole run", corr == 1, f"{corr}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--targets", type=int, default=50)
    p.add_argument("--aws-only", action="store_true")
    p.add_argument("--linux-only", action="store_true")
    args = p.parse_args()

    n = args.targets
    summary = {}

    if not args.linux_only:
        aws = run_aws_scale(n)
        summary["aws"] = aws
        exp = aws["expected_resources"]
        # 1 account + buckets + security groups + volumes.
        # moto auto-creates one default security group per VPC, so security groups
        # are counted from what the normalizer actually produced rather than assumed.
        verify_in_db(aws["run_id"], aws["results"], aws["resources"], "AWS")
        check(f"AWS: at least {n} resources normalized", aws["resources"] >= n,
              f"{aws['resources']}")
        check("AWS: outcomes are a MIX, not uniform",
              len([k for k, v in aws["outcomes"].items() if v > 0]) >= 2,
              str(aws["outcomes"]))

    if not args.aws_only:
        linux = run_linux_scale(n)
        summary["linux"] = linux
        print(f"\n  targets              : {linux['targets']}")
        print(f"  resources normalized : {linux['resources']}")
        print(f"  results persisted    : {linux['results']}")
        print(f"  collect (SSH, seq.)  : {linux['timings']['collect_s']}s")
        print(f"  evaluate             : {linux['timings']['evaluate_s']}s")
        print(f"  persist              : {linux['timings']['persist_s']}s")
        print(f"  TOTAL                : {linux['timings']['total_s']}s")
        if linux["targets"]:
            print(f"  per-target average   : "
                  f"{round(linux['timings']['collect_s'] / linux['targets'], 2)}s")

        verify_in_db(linux["run_id"], linux["results"], linux["resources"], "Linux")
        check(f"Linux: {n} distinct targets scanned", linux["resources"] == n,
              f"{linux['resources']}")
        check(f"Linux: results == {n} targets x 18 Linux controls",
              linux["results"] == n * 18, f"{linux['results']} vs {n * 18}")

        # 50 targets must mean 50 credential_used rows -- one per credential fetch.
        with get_engine().connect() as conn:
            creds = conn.execute(text(
                "SELECT count(*) FROM audit_log WHERE run_id = :r "
                "AND event_type = 'credential_used'"), {"r": linux["run_id"]}).scalar()
        check(f"Linux: {n} credential_used audit rows (one per target)",
              creds == n, f"{creds}")

    print()
    if _failures:
        print(f"{len(_failures)} CHECK(S) FAILED: {_failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
