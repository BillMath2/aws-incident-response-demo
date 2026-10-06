"""Read-only P06 deployment, artifact, boundary and budget assertions."""

import argparse
import base64
import json
from decimal import Decimal
from pathlib import Path

import boto3

from incident_demo.live.clients import sdk_config

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("use a new evidence file")
    sdk = boto3.Session(profile_name="incident-demo", region_name="us-east-2")
    config = sdk_config(20)
    if sdk.client("sts", config=config).get_caller_identity()["Account"] != "498084841421":
        raise ValueError("wrong account")
    evidence = ROOT / "docs/evidence/p06"
    outputs = json.loads((ROOT / "infra/cdk.out/retrieval-outputs.json").read_text())[
        "incident-demo-retrieval"
    ]
    live = json.loads((ROOT / "infra/cdk.out/live-outputs.json").read_text())["incident-demo-live"]
    checks, receipts = {}, []
    s3 = sdk.client("s3", config=config)
    for file in sorted(evidence.glob("live-*/response.json")):
        response = json.loads(file.read_text())
        stored = s3.get_object(Bucket=outputs["SourceBucketOutput"], Key=response["artifact_key"])
        with stored["Body"] as body:
            raw = json.loads(body.read(196609))
        checks[file.parent.name + "_artifact"] = raw == {
            k: v for k, v in response.items() if k != "artifact_key"
        }
        checks[file.parent.name + "_encryption"] = stored["ServerSideEncryption"] == "AES256"
        result = response["result"]
        checks[file.parent.name + "_limits"] = (
            result.get("usage", {}).get("model_calls", 0) <= 6
            and result.get("usage", {}).get("tool_calls", 0) <= 8
        )
        guards = [e for e in response["audit"] if e["event"] == "guardrail_finished"]
        if "permission_checks" in result:
            checks[file.parent.name + "_denials"] = all(
                code in {"AccessDenied", "AccessDeniedException"}
                for code in result["permission_checks"].values()
            )
        else:
            checks[file.parent.name + "_coverage"] = bool(guards) and all(
                e["coverage"]["guarded"] == e["coverage"]["total"] and e["guardrail_version"] == "1"
                for e in guards
            )
        receipts.append(
            {
                "run": file.parent.name,
                "status": result.get("status"),
                "reason": result.get("stop_reason"),
                "guardrail_checks": len(guards),
                "model_usage": result.get("usage"),
                "worker_ms": response["worker_latency_ms"],
                "artifact_key": response["artifact_key"],
            }
        )
    table = sdk.resource("dynamodb", config=config).Table("incident-demo-live-budget")
    global_item = table.get_item(Key={"pk": "global"}, ConsistentRead=True)["Item"]
    batch = table.get_item(Key={"pk": "batch#p06-dev-01"}, ConsistentRead=True)["Item"]
    ledger = json.loads((ROOT / "runs/p04-budget-ledger.json").read_text())
    local = sum(Decimal(r["reserved_usd"]) for r in ledger["reservations"])
    local_p06 = sum(
        Decimal(r["reserved_usd"])
        for r in ledger["reservations"]
        if r["batch_id"].startswith("p06-")
    )
    checks["budget_reconciled"] = local == global_item["reserved_cents"] / 100 + Decimal("0.10")
    checks["batch_reconciled"] = local_p06 == batch["reserved_cents"] / 100 <= 10
    checks["infrastructure_reserve_protected"] = local <= 40
    checks["lease_released"] = global_item["lease_until"] == 0
    control = sdk.client("bedrock-agentcore-control", config=config)
    runtime = control.get_agent_runtime(agentRuntimeId=live["RuntimeIdOutput"])
    endpoint = control.get_agent_runtime_endpoint(
        agentRuntimeId=live["RuntimeIdOutput"], endpointName="smoke"
    )
    checks["runtime_ready"] = runtime["status"] == "READY" and endpoint["status"] == "READY"
    checks["endpoint_current"] = runtime["agentRuntimeVersion"] == endpoint["liveVersion"]
    env = runtime["environmentVariables"]
    checks["pinned_runtime_config"] = (
        env["GUARDRAIL_VERSION"] == "1"
        and env["KNOWLEDGE_BASE_ID"] == outputs["KnowledgeBaseIdOutput"]
    )
    iam = sdk.client("iam", config=config)
    trust = iam.get_role(RoleName="incident-demo-knowledge")["Role"]["AssumeRolePolicyDocument"]
    checks["exact_kb_trust"] = (
        trust["Statement"][0]["Condition"]["ArnLike"]["aws:SourceArn"]
        == outputs["KnowledgeBaseArnOutput"]
    )
    checks["corpus_read_scope"] = "knowledge/p06-v1/*" in json.dumps(
        iam.get_role_policy(RoleName="incident-demo-knowledge", PolicyName="CorpusAndVectors")[
            "PolicyDocument"
        ]
    )
    model_logging = sdk.client(
        "bedrock", config=config
    ).get_model_invocation_logging_configuration()
    checks["raw_model_logging_disabled"] = not model_logging.get("loggingConfig")
    package = json.loads((ROOT / ".tools/p05-build/package.json").read_text())
    expected_sha = base64.b64encode(bytes.fromhex(package["sha256"])).decode()
    functions = sdk.client("lambda", config=config)
    for name in ("service-health", "recent-changes", "recent-logs"):
        actual = functions.get_function_configuration(FunctionName="incident-demo-diag-" + name)
        checks[name + "_package"] = actual["CodeSha256"] == expected_sha
    result = {
        "checks": checks,
        "passed": all(checks.values()),
        "runs": receipts,
        "runtime_version": runtime["agentRuntimeVersion"],
        "package_sha256": package["sha256"],
        "budget": {
            "local_total_reserved_usd": str(local),
            "p06_reserved_usd": str(local_p06),
            "cloud_global": global_item,
            "cloud_batch": batch,
        },
        "knowledge_trust": trust,
    }
    args.output.write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {"passed": result["passed"], "checks": len(checks), "budget": result["budget"]},
            default=str,
        )
    )
    if not result["passed"]:
        raise ValueError("failed readback assertions")


if __name__ == "__main__":
    main()
