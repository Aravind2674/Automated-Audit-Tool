"""
moto fixture set B — the INDEPENDENT cross-check scenario for spec Section 9 rule 8.

This is the moto equivalent of opening a fresh SSH connection in Phases 1-3: a second
source of truth built without reference to the first, so that agreement between the
collector/normalizer and this scenario means something.

Rules this file follows deliberately:

* It does not import from `aws_scenario_a`, and shares no helper code with it.
  Duplication here is the point — two fixture sets built from shared constructors can
  agree with each other about something neither AWS nor the collector would produce.
* Every resource has a different name, a different value, or a different shape from
  set A. Nothing is copied across.
* It exercises cases set A does NOT cover, because a cross-check that only repeats the
  first scenario's shapes verifies nothing beyond determinism:
    - a security group whose port RANGE contains 22 rather than equalling it
    - a security group using IpProtocol "-1" (all protocols, all ports)
    - a security group open to the world on a port that is NOT 22 (must still pass)
    - a CloudTrail trail that is multi-region AND logging AND has management event
      selectors — the passing direction, which set A never reaches
    - a multi-region trail that exists but is STOPPED

The expected outcomes below were derived by reading the AWS semantics, not by running
the collector and recording what it said.
"""

from __future__ import annotations

import boto3

REGION = "eu-west-1"


def build() -> dict:
    s3 = boto3.client("s3", region_name=REGION)
    ec2 = boto3.client("ec2", region_name=REGION)
    ct = boto3.client("cloudtrail", region_name=REGION)

    location = {"LocationConstraint": REGION}

    # ---- S3 -----------------------------------------------------------------
    # Fully blocked.
    s3.create_bucket(Bucket="beta-archive-secure", CreateBucketConfiguration=location)
    s3.put_public_access_block(
        Bucket="beta-archive-secure",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    # Exactly one flag off — a different partial shape from set A's.
    s3.create_bucket(Bucket="beta-reports-partial", CreateBucketConfiguration=location)
    s3.put_public_access_block(
        Bucket="beta-reports-partial",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": False,
        },
    )

    # ---- EC2 security groups ------------------------------------------------
    vpc = ec2.create_vpc(CidrBlock="172.31.0.0/16")["Vpc"]["VpcId"]

    # Port RANGE containing 22. A FromPort == 22 test would miss this entirely.
    sg_range = ec2.create_security_group(
        GroupName="beta-wide-range", Description="ports 20-30 open", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_range,
        IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 20, "ToPort": 30,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        }],
    )

    # IpProtocol "-1": all protocols, all ports. FromPort/ToPort are absent.
    sg_all = ec2.create_security_group(
        GroupName="beta-all-protocols", Description="everything open", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_all,
        IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
    )

    # Open to the world, but on HTTPS. This control is about SSH only, so it PASSES.
    # A parser that flagged any 0.0.0.0/0 rule would wrongly fail this.
    sg_https = ec2.create_security_group(
        GroupName="beta-public-https", Description="443 to world", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_https,
        IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        }],
    )

    # SSH from a specific host only.
    sg_narrow = ec2.create_security_group(
        GroupName="beta-bastion-only", Description="ssh from bastion", VpcId=vpc
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_narrow,
        IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
            "IpRanges": [{"CidrIp": "198.51.100.7/32"}],
        }],
    )

    # ---- EBS ----------------------------------------------------------------
    ec2.create_volume(AvailabilityZone=REGION + "a", Size=20, Encrypted=False)
    ec2.create_volume(AvailabilityZone=REGION + "b", Size=50, Encrypted=True)
    ec2.create_volume(AvailabilityZone=REGION + "b", Size=4, Encrypted=True)

    # ---- CloudTrail: a stopped multi-region trail AND a good one ------------
    s3.create_bucket(Bucket="beta-trail-bucket", CreateBucketConfiguration=location)

    ct.create_trail(
        Name="beta-stopped-trail",
        S3BucketName="beta-trail-bucket",
        IsMultiRegionTrail=True,
    )
    # deliberately NOT started

    ct.create_trail(
        Name="beta-good-trail",
        S3BucketName="beta-trail-bucket",
        IsMultiRegionTrail=True,
    )
    ct.start_logging(Name="beta-good-trail")
    ct.put_event_selectors(
        TrailName="beta-good-trail",
        EventSelectors=[{
            "ReadWriteType": "All",
            "IncludeManagementEvents": True,
            "DataResources": [],
        }],
    )

    return {
        "region": REGION,
        # Derived from AWS semantics, not from running the collector.
        "expected_by_resource": {
            "AWS-2.1.5": {
                "s3_bucket:beta-archive-secure": "pass",
                "s3_bucket:beta-reports-partial": "fail",
                "s3_bucket:beta-trail-bucket": "fail",
            },
            "AWS-5.2": {
                "security_group:" + sg_range: "fail",   # range 20-30 contains 22
                "security_group:" + sg_all: "fail",     # "-1" = all ports
                "security_group:" + sg_https: "pass",   # world-open, but not SSH
                "security_group:" + sg_narrow: "pass",  # /32 source
            },
            # AWS-3.1 passes here: beta-good-trail is multi-region, logging, with an
            # All/IncludeManagementEvents selector. The stopped trail must not be the
            # one chosen.
            "AWS-3.1": "pass",
            # moto defaults: no root MFA, no root access keys.
            "AWS-1.4": "pass",
            "AWS-1.5": "fail",
        },
        "encrypted_volume_count": 2,
        "unencrypted_volume_count": 1,
        "ids": {
            "sg_range": sg_range, "sg_all": sg_all,
            "sg_https": sg_https, "sg_narrow": sg_narrow, "vpc": vpc,
        },
    }
