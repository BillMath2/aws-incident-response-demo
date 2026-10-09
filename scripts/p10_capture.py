"""Read-only, bounded project inventory and sanitized evidence export for P10."""

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import boto3
import yaml
from botocore.config import Config

from incident_demo.contracts.base import content_hash

ACCOUNT = "498084841421"
REGION = "us-east-2"
STACKS = tuple(
    "incident-demo-" + name for name in ("foundation", "live", "retrieval", "workflow", "toolkit")
)
CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1})
PRIVATE_KEYS = {"token", "tasktoken", "accesskeyid", "secretaccesskey", "sessiontoken"}


class TemplateLoader(yaml.SafeLoader):
    """Preserve CloudFormation intrinsic tags without evaluating them."""


def intrinsic(loader, tag, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {tag if tag in {"Ref", "Condition"} else "Fn::" + tag: value}


TemplateLoader.add_multi_constructor("!", intrinsic)


def sanitize(value):
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if k.lower() not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, default=str) + "\n")


def collect(session, folder):
    if session.client("sts", config=CONFIG).get_caller_identity()["Account"] != ACCOUNT:
        raise ValueError("Wrong AWS account")
    folder.mkdir(parents=True, exist_ok=False)
    cf = session.client("cloudformation", config=CONFIG)
    stacks, resources = [], []
    for name in STACKS:
        stack = cf.describe_stacks(StackName=name)["Stacks"][0]
        template = cf.get_template(StackName=name)["TemplateBody"]
        if isinstance(template, str):
            template = yaml.load(template, Loader=TemplateLoader)
        write_json(folder / "templates" / (name + ".json"), template)
        stacks.append(
            {
                "name": name,
                "id": stack["StackId"],
                "status": stack["StackStatus"],
                "termination_protection": stack.get("EnableTerminationProtection", False),
                "outputs": stack.get("Outputs", []),
            }
        )
        for page in cf.get_paginator("list_stack_resources").paginate(StackName=name):
            for resource in page["StackResourceSummaries"]:
                definition = template["Resources"][resource["LogicalResourceId"]]
                resources.append(
                    {
                        "stack": name,
                        "logical_id": resource["LogicalResourceId"],
                        "type": resource["ResourceType"],
                        "physical_id": resource.get("PhysicalResourceId"),
                        "status": resource["ResourceStatus"],
                        "deletion_policy": definition.get("DeletionPolicy", "Delete"),
                        "replacement_policy": definition.get("UpdateReplacePolicy", "Delete"),
                    }
                )
    write_json(folder / "stack-inventory.json", {"stacks": stacks, "resources": resources})

    # Read deployment/recovery state without exporting private callback tokens.
    db = session.resource("dynamodb", config=CONFIG)
    tables = sorted({r["physical_id"] for r in resources if r["type"] == "AWS::DynamoDB::Table"})
    table_records = {}
    for name in tables:
        records = []
        for page in db.meta.client.get_paginator("scan").paginate(
            TableName=name, ConsistentRead=True
        ):
            for item in page["Items"]:
                if "document" in item:
                    item = item | {"document": json.loads(item["document"])}
                records.append(sanitize(item))
                if len(records) > 1000:
                    raise ValueError("Table export bound exceeded")
        write_json(folder / "tables" / (name + ".json"), records)
        table_records[name] = records

    s3 = session.client("s3", config=CONFIG)
    bucket = f"incident-demo-artifacts-{ACCOUNT}-{REGION}"
    artifacts, total_bytes = [], 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="runs/"):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.endswith(".json"):
                continue
            if item["Size"] > 2 * 1024**2 or len(artifacts) >= 512:
                raise ValueError("Artifact export bound exceeded")
            reply = s3.get_object(Bucket=bucket, Key=key)
            with reply["Body"] as stream:
                raw = stream.read(2 * 1024**2 + 1)
            total_bytes += len(raw)
            if len(raw) > 2 * 1024**2 or total_bytes > 64 * 1024**2:
                raise ValueError("Artifact export byte bound exceeded")
            document = json.loads(raw)
            cleaned = sanitize(document)
            # Hash-based filenames cannot escape the export directory through object keys.
            filename = "artifacts/" + sha256(key.encode()).hexdigest() + ".json"
            write_json(folder / filename, cleaned)
            artifacts.append(
                {
                    "bucket": bucket,
                    "key": key,
                    "version_id": reply.get("VersionId"),
                    "etag": reply.get("ETag"),
                    "source_sha256": sha256(raw).hexdigest(),
                    "document_sha256": content_hash(document),
                    "file": filename,
                    "export_sha256": sha256((folder / filename).read_bytes()).hexdigest(),
                    "redacted": cleaned != document,
                }
            )
    write_json(folder / "artifact-manifest.json", artifacts)
    lookup = {item["key"]: item for item in artifacts}
    runs = [
        r["document"]
        for r in table_records.get("incident-demo-p07-runs", [])
        if r["pk"].startswith("run#")
    ]
    for run in runs:
        for kind in ("artifact", "verification"):
            if run.get(kind):
                ref = run[kind]
                if lookup.get(ref["key"], {}).get("document_sha256") != ref["sha256"]:
                    raise ValueError("Run artifact missing or hash differs")

    logs = session.client("logs", config=CONFIG)
    groups = {}
    for prefix in ("/incident-demo/", "/aws/bedrock-agentcore/runtimes/incident_demo_"):
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
            for group in page["logGroups"]:
                groups[group["logGroupName"]] = {
                    k: group.get(k)
                    for k in ("logGroupName", "retentionInDays", "storedBytes", "kmsKeyId")
                }
    iam = session.client("iam", config=CONFIG)
    policies = []
    for page in iam.get_paginator("list_policies").paginate(Scope="Local"):
        for policy in page["Policies"]:
            if policy["PolicyName"].startswith("incident-demo-"):
                policies.append({k: policy[k] for k in ("PolicyName", "Arn", "AttachmentCount")})
    write_json(
        folder / "additional-inventory.json",
        {
            "project_log_groups": list(groups.values()),
            "project_managed_policies": policies,
            "scope_note": "Stack resources plus named project logs/policies. Historical replaced "
            "or untagged resources, object versions and backups require cleanup reconciliation.",
        },
    )
    summary = {
        "at": datetime.now(UTC).isoformat(),
        "account": ACCOUNT,
        "region": REGION,
        "stacks": len(stacks),
        "resources": len(resources),
        "tables_exported": len(tables),
        "run_artifacts_exported": len(artifacts),
        "artifact_bytes_read": total_bytes,
        "workflow_runs": [{"run_id": r["run_id"], "status": r["status"]} for r in runs],
        "active_workflows": [
            r["run_id"]
            for r in runs
            if r["status"]
            not in {"resolved", "unresolved", "rejected", "expired", "escalated", "failed"}
        ],
        "stack_statuses_complete": all(
            s["status"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"} for s in stacks
        ),
        "cloud_mutations": 0,
        "model_calls": 0,
        "cleanup_complete": False,
        "export_scope": "Current JSON objects under runs/ plus sanitized table state; "
        "not a full bucket version, CloudTrail or CloudWatch archive",
    }
    write_json(folder / "summary.json", summary)
    files = {
        p.relative_to(folder).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file()
    }
    write_json(folder / "files.json", files)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name="incident-demo", region_name=REGION)
    print(json.dumps(collect(session, args.output), indent=2))


if __name__ == "__main__":
    main()
