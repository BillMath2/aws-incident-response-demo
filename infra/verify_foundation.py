"""Read back deployed protection settings and retain an inventory. No data mutation."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from manage import aws, verify_identity
from settings import ROOT, load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("use a new evidence path")
    config = load_config()
    identity = verify_identity(config)
    stack = aws(config, "cloudformation", "describe-stacks", "--stack-name", config["stack_name"])[
        "Stacks"
    ][0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    buckets = {}
    for key in ("ArtifactBucket", "AccessLogBucket"):
        name = outputs[key]
        buckets[key] = {
            "name": name,
            "public_access": aws(config, "s3api", "get-public-access-block", "--bucket", name),
            "encryption": aws(config, "s3api", "get-bucket-encryption", "--bucket", name),
            "ownership": aws(config, "s3api", "get-bucket-ownership-controls", "--bucket", name),
            "lifecycle": aws(
                config, "s3api", "get-bucket-lifecycle-configuration", "--bucket", name
            ),
            "policy": json.loads(
                aws(config, "s3api", "get-bucket-policy", "--bucket", name)["Policy"]
            ),
        }
    buckets["ArtifactBucket"]["logging"] = aws(
        config, "s3api", "get-bucket-logging", "--bucket", outputs["ArtifactBucket"]
    )
    buckets["ArtifactBucket"]["versioning"] = aws(
        config, "s3api", "get-bucket-versioning", "--bucket", outputs["ArtifactBucket"]
    )
    table = aws(
        config,
        "dynamodb",
        "describe-table",
        "--table-name",
        outputs["StateTable"],
        "--query",
        "Table.{status:TableStatus,billing:BillingModeSummary,"
        "caps:OnDemandThroughput,deletion_protection:DeletionProtectionEnabled}",
    )
    ttl = aws(config, "dynamodb", "describe-time-to-live", "--table-name", outputs["StateTable"])
    pitr = aws(
        config, "dynamodb", "describe-continuous-backups", "--table-name", outputs["StateTable"]
    )
    log_groups = aws(
        config,
        "logs",
        "describe-log-groups",
        "--log-group-name-prefix",
        outputs["AuditLogGroup"],
        "--query",
        "logGroups[].{name:logGroupName,days:retentionInDays}",
    )
    inventory = aws(
        config,
        "cloudformation",
        "list-stack-resources",
        "--stack-name",
        config["stack_name"],
        "--query",
        "StackResourceSummaries[].{type:ResourceType,id:PhysicalResourceId,status:ResourceStatus}",
    )
    checks = {
        "stack_complete": stack["StackStatus"] in ("CREATE_COMPLETE", "UPDATE_COMPLETE"),
        "termination_protection": stack["EnableTerminationProtection"],
        "buckets_private": all(
            all(b["public_access"]["PublicAccessBlockConfiguration"].values())
            for b in buckets.values()
        ),
        "buckets_tls_only": all(
            any(
                s.get("Effect") == "Deny"
                and s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false"
                for s in b["policy"]["Statement"]
            )
            for b in buckets.values()
        ),
        "artifact_versioned": buckets["ArtifactBucket"]["versioning"].get("Status") == "Enabled",
        "access_logging": buckets["ArtifactBucket"]["logging"]
        .get("LoggingEnabled", {})
        .get("TargetBucket")
        == outputs["AccessLogBucket"],
        "table_active": table["status"] == "ACTIVE",
        "on_demand": table["billing"]["BillingMode"] == "PAY_PER_REQUEST",
        "capacity_capped": table["caps"] == {"MaxReadRequestUnits": 10, "MaxWriteRequestUnits": 10},
        "table_deletion_protection": table["deletion_protection"],
        "ttl_enabled": ttl["TimeToLiveDescription"]["TimeToLiveStatus"] == "ENABLED",
        "pitr_enabled": pitr["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"][
            "PointInTimeRecoveryStatus"
        ]
        == "ENABLED",
        "log_retention": {"name": outputs["AuditLogGroup"], "days": 7} in log_groups,
    }
    template = ROOT / "cdk.out" / (config["stack_name"] + ".template.json")
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        **identity,
        "checks": checks,
        "outputs": outputs,
        "buckets": buckets,
        "table": table,
        "ttl": ttl,
        "pitr": pitr,
        "log_groups": log_groups,
        "resources": inventory,
        "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
        "runtime_authorization_tested": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(checks, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
