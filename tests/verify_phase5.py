"""
Phase 5 verification: AWS collector against moto, plus rule 8 cross-check.

Runs BOTH fixture scenarios:

  set A  — the scenario the collector and normalizer were built against
  set B  — an independently written scenario (spec Section 9 rule 8), exercising
           shapes set A never produces

and asserts the spec Section 1 constraint that the collector uses boto3's client
interface only.

Usage:
    python tests/verify_phase5.py
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(pathlib.Path(__file__).parent / "fixtures"))

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from moto import mock_aws  # noqa: E402

from collectors.aws_collector import AWSCollector  # noqa: E402
from control_library import load_controls  # noqa: E402
from engine.evaluator import evaluate  # noqa: E402
from engine.normalizer import _parse_iam_root, normalize  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))
        _failures.append(label)


def _aws_controls() -> dict:
    return {c["id"]: c for c in load_controls() if c["id"].startswith("AWS-")}


def _run(scenario, region: str):
    meta = scenario.build()
    docs = AWSCollector(region=region).collect(
        {"target_id": "verify-phase5", "region": region}
    )
    resources = normalize(docs, "aws")
    outcomes: dict[str, dict[str, str]] = {}
    for control in _aws_controls().values():
        for result in evaluate(control, resources):
            outcomes.setdefault(control["id"], {})[result["resource_id"]] = result["outcome"]
    return meta, resources, outcomes


def test_client_interface_only() -> None:
    """Spec Section 1: boto3 client interface only, never .resource()."""
    print("\n=== Spec Section 1: boto3 client interface only ===\n")
    source = (REPO_ROOT / "backend" / "collectors" / "aws_collector.py").read_text(
        encoding="utf-8"
    )
    # Strip the module docstring so the prohibition described in prose is not
    # mistaken for a usage of the thing it prohibits.
    body = re.sub(r'^""".*?"""', "", source, count=1, flags=re.S)

    check("no boto3.resource( in aws_collector.py", ".resource(" not in body)
    check("session.client( is used", ".client(" in body)

    mutating = re.findall(
        r"\.(create_(?!_)|delete_|put_(?!public_access_block\b)|update_|modify_|"
        r"terminate_|attach_|detach_|revoke_|authorize_)\w*\(",
        body,
    )
    check("no mutating API calls in the collector", not mutating, str(mutating[:5]))


def test_scenario(name: str, scenario, region: str) -> None:
    print(f"\n=== Scenario {name} ===\n")
    with mock_aws():
        meta, resources, outcomes = _run(scenario, region)

    kinds = {}
    for r in resources:
        kinds[r["resource_type"]] = kinds.get(r["resource_type"], 0) + 1
    print(f"  resources normalized: {kinds}")
    check("collector_type does not leak into normalized resources",
          all("collector_type" not in r for r in resources))

    expected = meta.get("expected_by_resource") or {}
    for control_id, want in expected.items():
        if isinstance(want, str):
            got = list(outcomes.get(control_id, {}).values())
            check(f"{control_id} (account-level) == {want}",
                  bool(got) and all(g == want for g in got), str(got))
        else:
            for resource_id, w in want.items():
                g = outcomes.get(control_id, {}).get(resource_id, "MISSING")
                check(f"{control_id} {resource_id.split(':')[-1][:28]} == {w}", g == w, g)

    if "encrypted_volume_count" in meta:
        enc = sum(1 for r in resources if r["resource_type"] == "ebs_volume"
                  and r["attributes"]["ebs_volume"]["encrypted"])
        unenc = sum(1 for r in resources if r["resource_type"] == "ebs_volume"
                    and not r["attributes"]["ebs_volume"]["encrypted"])
        check("AWS-2.2.1 encrypted volume count",
              enc == meta["encrypted_volume_count"], f"{enc}")
        check("AWS-2.2.1 unencrypted volume count",
              unenc == meta["unencrypted_volume_count"], f"{unenc}")


def test_iam_root_branches_unreachable_under_moto() -> None:
    """The root-account branches moto cannot reach end to end.

    moto does not model the root user: AccountMFAEnabled and
    AccountAccessKeysPresent are fixed at 0 and cannot be changed. AWS-1.5 is
    therefore only ever exercised in the `fail` direction and AWS-1.4 only in the
    `pass` direction. These parser-level checks confirm the LOGIC is right; they are
    NOT equivalent to observing a real account, and Phase 5 remains open on that
    basis. See architecture.md 3.6.
    """
    print("\n=== iam_root branches moto cannot reach (parser-level only) ===\n")
    controls = _aws_controls()

    def summary(mfa: int, keys: int) -> dict:
        return {"calls": [{"api": "iam:GetAccountSummary", "ok": True, "error": None,
                           "data": {"SummaryMap": {"AccountMFAEnabled": mfa,
                                                   "AccountAccessKeysPresent": keys}}}]}

    def outcomes_for(mfa: int, keys: int) -> tuple[str, str]:
        attrs = _parse_iam_root(summary(mfa, keys))
        res = [{"resource_type": "aws_account", "resource_id": "aws_account:test",
                "attributes": {"iam_root": attrs}}]
        return (evaluate(controls["AWS-1.5"], res)[0]["outcome"],
                evaluate(controls["AWS-1.4"], res)[0]["outcome"])

    check("MFA off, no keys  -> 1.5 fail / 1.4 pass", outcomes_for(0, 0) == ("fail", "pass"))
    check("MFA on,  no keys  -> 1.5 pass / 1.4 pass", outcomes_for(1, 0) == ("pass", "pass"))
    check("MFA off, 2 keys   -> 1.5 fail / 1.4 fail", outcomes_for(0, 2) == ("fail", "fail"))
    check("MFA on,  1 key    -> 1.5 pass / 1.4 fail", outcomes_for(1, 1) == ("pass", "fail"))

    denied = {"calls": [{"api": "iam:GetAccountSummary", "ok": False,
                         "error": "AccessDenied", "data": None}]}
    res = [{"resource_type": "aws_account", "resource_id": "aws_account:test",
            "attributes": {"iam_root": _parse_iam_root(denied)}}]
    check("AccessDenied -> error, never fail",
          evaluate(controls["AWS-1.5"], res)[0]["outcome"] == "error")


def main() -> int:
    import aws_scenario_a
    import aws_scenario_b

    test_client_interface_only()
    test_scenario("A (built against)", aws_scenario_a, "us-east-1")
    test_scenario("B (independent, rule 8)", aws_scenario_b, aws_scenario_b.REGION)
    test_iam_root_branches_unreachable_under_moto()

    print()
    if _failures:
        print(f"{len(_failures)} CHECK(S) FAILED: {_failures}")
        return 1
    print("all checks passed")
    print("\nNOTE: moto is a mock. Phase 5 is NOT verified to the standard of Phases")
    print("1-4, which ran against a live VM. See architecture.md 3.6 -- this phase")
    print("needs re-validation against a real AWS account before its findings can be")
    print("trusted the way the Linux findings now are.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
