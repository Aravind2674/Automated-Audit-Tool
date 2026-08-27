"""
AWS collector. Reads account state through the boto3 **client** interface and returns
it raw.

Two constraints from the spec are structural here, not stylistic:

1.  **`boto3.client(...)` only — never `boto3.resource(...)`** (spec Section 1). AWS
    has placed the resource interface in permanent feature freeze and confirmed it
    will not carry into the next major SDK version, so building against it now means
    building on something already being removed. `tests/verify_phase5.py` greps this
    module to assert `.resource(` never appears.

2.  **Read-only.** Every call below is a `Describe*`, `List*` or `Get*`. Nothing
    creates, modifies or deletes. The documented IAM requirement is the AWS-managed
    `SecurityAudit` or `ViewOnlyAccess` policy and nothing more. An audit tool holding
    write credentials across an estate is a high-value target; read-only by
    construction bounds a compromise of this tool to disclosure rather than control.

As in the SSH collector, an API call that fails is **evidence, not an exception**.
`GetPublicAccessBlock` raises `NoSuchPublicAccessBlockConfiguration` when a bucket has
no block configuration at all — which is precisely the finding AWS-2.1.5 exists to
catch, not an error to propagate. Such failures are recorded in the raw doc with their
error code. Only a failure that prevents collection entirely — no credentials, region
unreachable — raises `CollectorError`.
"""

from __future__ import annotations

import datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .base import Collector, CollectorError


def _api(name: str, ok: bool, data, error: str | None = None) -> dict:
    return {"api": name, "ok": ok, "data": data, "error": error}


def _call(name: str, fn, **kwargs) -> dict:
    """Invoke one read-only API call, capturing a client error as evidence."""
    try:
        return _api(name, True, fn(**kwargs))
    except ClientError as exc:
        return _api(
            name, False, None, exc.response.get("Error", {}).get("Code", "ClientError")
        )


class AWSCollector(Collector):
    """Collects raw AWS account state via boto3 clients."""

    collector_type = "aws"

    def __init__(self, region: str = "us-east-1") -> None:
        self.region = region

    # -- per-source collection ----------------------------------------------------

    def _collect_iam_root(self, session) -> dict:
        """Root account MFA and access-key state, from the IAM account summary.

        `GetAccountSummary` is used rather than `GetLoginProfile`/`ListAccessKeys`
        because the root user's keys cannot be enumerated by any IAM caller other than
        root itself — the summary counters are the only read-only path to this that a
        SecurityAudit-scoped principal actually has.
        """
        iam = session.client("iam", region_name=self.region)
        return {
            "calls": [
                _call("iam:GetAccountSummary", iam.get_account_summary),
                _call("iam:ListAccountAliases", iam.list_account_aliases),
            ]
        }

    def _collect_s3_buckets(self, session) -> dict:
        s3 = session.client("s3", region_name=self.region)
        calls = [_call("s3:ListBuckets", s3.list_buckets)]

        names = []
        if calls[0]["ok"]:
            names = [b["Name"] for b in calls[0]["data"].get("Buckets", [])]

        for name in names:
            # A bucket with no block-public-access configuration raises
            # NoSuchPublicAccessBlockConfiguration. That is the finding, not an error.
            calls.append(
                _call(
                    f"s3:GetPublicAccessBlock:{name}",
                    s3.get_public_access_block,
                    Bucket=name,
                )
            )
        return {"calls": calls, "bucket_names": names}

    def _collect_security_groups(self, session) -> dict:
        ec2 = session.client("ec2", region_name=self.region)
        return {"calls": [_call("ec2:DescribeSecurityGroups", ec2.describe_security_groups)]}

    def _collect_ebs_volumes(self, session) -> dict:
        ec2 = session.client("ec2", region_name=self.region)
        return {"calls": [_call("ec2:DescribeVolumes", ec2.describe_volumes)]}

    def _collect_cloudtrail(self, session) -> dict:
        ct = session.client("cloudtrail", region_name=self.region)
        calls = [_call("cloudtrail:DescribeTrails", ct.describe_trails)]

        trails = []
        if calls[0]["ok"]:
            trails = calls[0]["data"].get("trailList", [])

        for trail in trails:
            name = trail.get("TrailARN") or trail.get("Name")
            # A trail can exist, be multi-region, and still be stopped. Status and
            # event selectors are collected per trail so "configured" and "actually
            # logging" can be distinguished.
            calls.append(_call(f"cloudtrail:GetTrailStatus:{name}", ct.get_trail_status, Name=name))
            calls.append(
                _call(
                    f"cloudtrail:GetEventSelectors:{name}",
                    ct.get_event_selectors,
                    TrailName=name,
                )
            )
        return {"calls": calls}

    _SOURCES = {
        "iam_root": _collect_iam_root,
        "s3_bucket": _collect_s3_buckets,
        "security_group": _collect_security_groups,
        "ebs_volume": _collect_ebs_volumes,
        "cloudtrail": _collect_cloudtrail,
    }

    # -- Collector interface ------------------------------------------------------

    def collect(self, target: dict) -> list[dict]:
        """Returns raw provider-specific state docs. Never touches evaluation logic.

        target keys:
            target_id   required -- stable identifier for the audited account
            region      optional -- defaults to the collector's region
            sources     optional -- defaults to all
        """
        if "target_id" not in target:
            raise CollectorError("target is missing required key 'target_id'")

        region = target.get("region", self.region)
        sources = target.get("sources") or sorted(self._SOURCES)
        unknown = [s for s in sources if s not in self._SOURCES]
        if unknown:
            raise CollectorError(f"no API mapping for source(s): {unknown}")

        # TODO (spec Section 6): credentials must come from
        # secrets_manager.get_credential(target_id), which must also write a
        # credential_used audit row. Currently boto3's default chain is used, exactly
        # as the SSH collector still takes credentials from its target dict. Deferred,
        # not skipped -- must close before Phase 7.
        session = boto3.Session(region_name=region)

        try:
            account_id = session.client("sts", region_name=region).get_caller_identity()["Account"]
        except (ClientError, BotoCoreError) as exc:
            raise CollectorError(
                f"cannot collect from AWS account {target['target_id']} in {region}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        docs: list[dict] = []
        for source in sources:
            payload = self._SOURCES[source](self, session)
            docs.append(
                {
                    "source": source,
                    "collector_type": self.collector_type,
                    "target_id": target["target_id"],
                    "account_id": account_id,
                    "region": region,
                    "collected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    **payload,
                }
            )
        return docs
