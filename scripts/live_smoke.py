"""Invoke the private IAM-authenticated AgentCore endpoint with retained evidence."""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from time import monotonic
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config

from incident_demo.live.contracts import LiveRequest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "infra"))
from budget import reserve  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[f"case-{n:03}" for n in range(1, 9)], default="case-001")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--deadline", type=float, default=120)
    parser.add_argument("--model-calls", type=int, default=6)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--initialize-budget", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sdk = boto3.Session(profile_name="incident-demo", region_name="us-east-2")
    config = Config(
        connect_timeout=5, read_timeout=150, retries={"total_max_attempts": 1, "mode": "standard"}
    )
    if sdk.client("sts", config=config).get_caller_identity()["Account"] != "498084841421":
        raise ValueError("wrong deployment account")
    outputs = json.loads((ROOT / "infra/cdk.out/live-outputs.json").read_text())[
        "incident-demo-live"
    ]
    if args.initialize_budget:
        table = sdk.resource("dynamodb", config=config).Table(outputs["BudgetTableOutput"])
        try:
            table.put_item(
                Item={"pk": "global", "reserved_cents": 0, "lease_until": 0},
                ConditionExpression=Attr("pk").not_exists(),
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            pass  # Never reset a live ledger.
    mapping = json.loads((ROOT / ".tools/p05-build/package.json").read_text())[
        "development_telemetry"
    ]
    fixture = json.loads((ROOT / f"fixtures/cases/{args.case}.json").read_text())
    request = LiveRequest.model_validate_json(
        json.dumps(
            {
                "run_id": "p05-" + uuid4().hex,
                "batch_id": args.batch,
                "telemetry_id": mapping[args.case],
                "incident": fixture["incident"],
                "operation": "permission_probe" if args.probe else "investigate",
                "settings": {
                    "model": "us.amazon.nova-lite-v1:0",
                    "limits": {"deadline_seconds": args.deadline, "model_calls": args.model_calls},
                },
            }
        )
    )
    (args.output / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
    reserve(request.run_id, Decimal("0.25"))
    client = sdk.client("bedrock-agentcore", config=config)
    session_id = str(uuid4())
    started = monotonic()
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=outputs["RuntimeArnOutput"],
            runtimeSessionId=session_id,
            qualifier="smoke",
            contentType="application/json",
            payload=request.model_dump_json().encode(),
        )
        with response["response"] as stream:
            raw = stream.read(196609)
        if len(raw) > 196608:
            raise ValueError("oversized runtime response")
        (args.output / "response.json").write_bytes(raw)
        (args.output / "transport.json").write_text(
            json.dumps(
                {
                    "latency_ms": int((monotonic() - started) * 1000),
                    "session_id": session_id,
                    "aws_request_id": response["ResponseMetadata"]["RequestId"],
                    "status": response.get("statusCode"),
                    "reservation_usd": "0.25",
                },
                indent=2,
            )
        )
        result = json.loads(raw)
        print(json.dumps({"run_id": request.run_id, "result": result.get("result", result)}))
    except Exception as exc:
        (args.output / "failure.json").write_text(
            json.dumps(
                {"category": type(exc).__name__, "message": str(exc), "reservation_retained": True},
                indent=2,
            )
        )
        raise
    finally:
        try:
            client.stop_runtime_session(
                agentRuntimeArn=outputs["RuntimeArnOutput"],
                runtimeSessionId=session_id,
                qualifier="smoke",
            )
        except Exception as exc:
            (args.output / "session-stop-error.json").write_text(
                json.dumps({"category": type(exc).__name__})
            )


if __name__ == "__main__":
    main()
