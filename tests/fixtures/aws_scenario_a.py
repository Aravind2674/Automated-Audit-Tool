"""
moto fixture set A — the scenario the AWS collector and normalizer are BUILT against.

Deliberately mixed, for the same reason the demo VM is: a scenario where everything
fails cannot distinguish a correct evaluator from one that returns `fail`
unconditionally.

Set B (`aws_scenario_b.py`) is written independently for rule 8's cross-check. Do not
import from this module there, and do not refactor shared helpers between them — the
duplication is the point. Two fixture sets that share construction code can agree with
each other about something neither AWS nor the collector would ever produce.
"""

from __future__ import annotations

import boto3

REGION = "us-east-1"


def build() -> dict:
    """Create scenario A inside an active moto mock. Returns the expected posture."""
    s3 = boto3.client("s3", region_name=REGION)
    ec2 = boto3.client("ec2", region_name=REGION)
    ct = boto3.client("cloudtrail", region_name=REGION)

    # ---- S3: one locked-down bucket, one wide open --------------------------
    s3.create_bucket(Bucket="audit-demo-locked")
    s3.put_public_access_block(
        Bucket="audit-demo-locked",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    # No block configuration at all -> GetPublicAccessBlock raises
    # NoSuchPublicAccessBlockConfiguration, which the collector records as evidence.
    s3.create_bucket(Bucket="audit-demo-open")

    # A partial configuration is its own failure mode: it looks configured but
    # leaves a path to exposure open.
    s3.create_bucket(Bucket="audit-demo-partial")
    s3.put_public_access_block(
        Bucket="audit-demo-partial",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": False,
            "RestrictPublicBuckets": False,
        },
    )

    # ---- EC2 security groups ------------------------------------------------
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]

    sg_open = ec2.create_security_group(
        GroupName="ssh-open-to-world", Description="intentionally open", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_open,
        IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        }],
    )

    sg_ipv6 = ec2.create_security_group(
        GroupName="ssh-open-ipv6-only", Description="ipv6 any", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_ipv6,
        IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
            "Ipv6Ranges": [{"CidrIpv6": "::/0"}],
        }],
    )

    sg_ok = ec2.create_security_group(
        GroupName="ssh-restricted", Description="office range only", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_ok,
        IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
            "IpRanges": [{"CidrIp": "203.0.113.0/24"}],
        }],
    )

    # ---- EBS volumes --------------------------------------------------------
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=8, Encrypted=True)
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=8, Encrypted=False)

    # ---- CloudTrail: single-region only, which is the trap -----------------
    s3.create_bucket(Bucket="audit-demo-trail-logs")
    ct.create_trail(
        Name="single-region-trail",
        S3BucketName="audit-demo-trail-logs",
        IsMultiRegionTrail=False,
    )
    ct.start_logging(Name="single-region-trail")

    return {
        "region": REGION,
        "expected_by_resource": {
            # root MFA off and no root keys are moto's defaults -- asserted rather
            # than assumed, so that a change in moto's behaviour is caught.
            "AWS-1.4": "pass",
            "AWS-1.5": "fail",
            "AWS-3.1": "fail",  # only a single-region trail exists
            "AWS-2.1.5": {
                "s3_bucket:audit-demo-locked": "pass",
                "s3_bucket:audit-demo-open": "fail",
                "s3_bucket:audit-demo-partial": "fail",
                "s3_bucket:audit-demo-trail-logs": "fail",
            },
            "AWS-5.2": {
                "security_group:" + sg_open: "fail",
                "security_group:" + sg_ipv6: "fail",
                "security_group:" + sg_ok: "pass",
            },
        },
        "encrypted_volume_count": 1,
        "unencrypted_volume_count": 1,
        "ids": {"sg_open": sg_open, "sg_ipv6": sg_ipv6, "sg_ok": sg_ok, "vpc": vpc},
    }
