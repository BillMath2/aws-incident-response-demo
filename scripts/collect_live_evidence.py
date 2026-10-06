"""Read-only live inventory and audit snapshot; requires an unused destination."""

import argparse
import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", default="p05-dev-01")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sdk = boto3.Session(profile_name="incident-demo", region_name="us-east-2")
    config = Config(connect_timeout=5, read_timeout=20, retries={"total_max_attempts": 1})

    def client(service):
        return sdk.client(service, config=config)

    def save(name, value):
        if isinstance(value, dict):
            value.pop("ResponseMetadata", None)
        (args.output / (name + ".json")).write_text(
            json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8"
        )

    assert client("sts").get_caller_identity()["Account"] == "498084841421"
    outputs = json.loads((ROOT / "infra/cdk.out/live-outputs.json").read_text())[
        "incident-demo-live"
    ]
    save("outputs", outputs)
    control = client("bedrock-agentcore-control")
    save("runtime", control.get_agent_runtime(agentRuntimeId=outputs["RuntimeIdOutput"]))
    save(
        "endpoint",
        control.get_agent_runtime_endpoint(
            agentRuntimeId=outputs["RuntimeIdOutput"], endpointName="smoke"
        ),
    )
    save("stack", client("cloudformation").describe_stacks(StackName="incident-demo-live"))
    save("resources", client("cloudformation").list_stack_resources(StackName="incident-demo-live"))
    iam = client("iam")
    role = "incident-demo-investigator"
    save("investigator-trust", iam.get_role(RoleName=role))
    for name in iam.list_role_policies(RoleName=role)["PolicyNames"]:
        save("investigator-policy", iam.get_role_policy(RoleName=role, PolicyName=name))
    save(
        "budget-global",
        client("dynamodb").get_item(
            TableName=outputs["BudgetTableOutput"], Key={"pk": {"S": "global"}}, ConsistentRead=True
        ),
    )
    save(
        "budget-batch",
        client("dynamodb").get_item(
            TableName=outputs["BudgetTableOutput"],
            Key={"pk": {"S": "batch#" + args.batch}},
            ConsistentRead=True,
        ),
    )
    save("budget-table", client("dynamodb").describe_table(TableName=outputs["BudgetTableOutput"]))
    save(
        "logs-key-rotation",
        client("kms").get_key_rotation_status(KeyId=outputs["LogsKeyArnOutput"]),
    )
    save("trail-status", client("cloudtrail").get_trail_status(Name="incident-demo-p05"))
    save("trail-selectors", client("cloudtrail").get_event_selectors(TrailName="incident-demo-p05"))
    s3 = client("s3")
    prefix = "AWSLogs/498084841421/CloudTrail/us-east-2/" + datetime.now(UTC).strftime("%Y/%m/%d/")
    objects = (
        s3.get_paginator("list_objects_v2")
        .paginate(
            Bucket=outputs["TrailBucketOutput"],
            Prefix=prefix,
            PaginationConfig={"MaxItems": 500, "PageSize": 100},
        )
        .build_full_result()
    )
    selected = sorted(objects.get("Contents", []), key=lambda obj: obj["LastModified"])[-50:]
    retrieval_path = ROOT / "infra/cdk.out/retrieval-outputs.json"
    resource_names = ["incident_demo_investigator", "incident-demo-diag-"]
    if retrieval_path.exists():
        retrieval = json.loads(retrieval_path.read_text())["incident-demo-retrieval"]
        resource_names += [retrieval["KnowledgeBaseArnOutput"], retrieval["GuardrailArnOutput"]]
    events = []
    for obj in selected:
        if not obj["Key"].endswith(".json.gz") or obj["Size"] > 1048576:
            continue
        response = s3.get_object(Bucket=outputs["TrailBucketOutput"], Key=obj["Key"])
        with response["Body"] as body:
            records = json.loads(gzip.decompress(body.read(1048577)))["Records"]
        for event in records:
            resources = json.dumps(event.get("resources", []))
            if event.get("eventCategory") != "Data" or not any(
                name in resources for name in resource_names
            ):
                continue
            events.append(
                {
                    "source_object": obj["Key"],
                    **{
                        field: event.get(field)
                        for field in (
                            "eventTime",
                            "eventName",
                            "eventSource",
                            "eventID",
                            "requestID",
                            "eventCategory",
                            "awsRegion",
                            "resources",
                            "errorCode",
                        )
                    },
                    "principal": event.get("userIdentity", {}).get("arn"),
                }
            )
    save(
        "trail-data-events",
        {
            "events": events,
            "objects_examined": len(selected),
            "objects_listed": len(objects.get("Contents", [])),
            "listing_truncated": bool(objects.get("NextToken")),
        },
    )
    save("alarms", client("cloudwatch").describe_alarms(AlarmNamePrefix="incident-demo-p05-"))
    save(
        "failure-alarm-history",
        client("cloudwatch").describe_alarm_history(
            AlarmName="incident-demo-p05-failures", HistoryItemType="StateUpdate", MaxRecords=20
        ),
    )
    for metric in ("Failures", "WorkerLatencyMs"):
        save(
            "metric-" + metric,
            client("cloudwatch").get_metric_statistics(
                Namespace="IncidentDemo/P05",
                MetricName=metric,
                StartTime=datetime.now(UTC) - timedelta(hours=2),
                EndTime=datetime.now(UTC),
                Period=60,
                Statistics=["Sum", "Maximum", "SampleCount"],
            ),
        )
    logs = client("logs")
    since = int((datetime.now(UTC) - timedelta(hours=2)).timestamp() * 1000)
    groups = []
    for prefix in (
        "/aws/bedrock-agentcore/runtimes/incident_demo_investigator",
        "/aws/lambda/incident-demo-diag-",
    ):
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
            groups.extend(page["logGroups"])
    save("log-groups", groups)
    for index, group in enumerate(groups):
        events = []
        for page in logs.get_paginator("filter_log_events").paginate(
            logGroupName=group["logGroupName"],
            startTime=since,
            PaginationConfig={"MaxItems": 1000},
        ):
            events.extend(page["events"])
        save(f"logs-{index}", {"group": group["logGroupName"], "events": events, "limit": 1000})
    save("snapshot", {"at": datetime.now(UTC).isoformat(), "read_only": True})
    print(f"Saved live inventory and bounded log snapshots to {args.output}")


if __name__ == "__main__":
    main()
