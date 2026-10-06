"""One tiny Converse call per selected text model; no corpus, tools, or action execution."""

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from budget import reserve, text_cost
from manage import aws, verify_identity
from settings import ROOT, load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Reserve a new output location before any billable request.
    args.output.mkdir(parents=True, exist_ok=False)
    config = load_config()
    identity = verify_identity(config)
    models = json.loads((ROOT / "models.json").read_text())["text"]
    batch_id = "p04-smoke-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    reservation = Decimal("0.10")
    # 1K input is a deliberately conservative bound for this fixed, tiny ASCII prompt.
    planned = sum(text_cost(m["price_usage_prefix"], 1000, 32) for m in models)
    if planned > reservation:
        raise ValueError("smoke exceeds fixed reservation")
    reserve(batch_id, reservation)
    os.environ["AWS_MAX_ATTEMPTS"] = "1"
    request = {
        "messages": [{"role": "user", "content": [{"text": "Reply with only READY."}]}],
        "inferenceConfig": {"maxTokens": 32, "temperature": 0},
    }
    results = []
    for model in models:
        request["modelId"] = model["inference_profile"]
        request_path = args.output / f"{model['role']}-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        try:
            response = aws(
                config,
                "bedrock-runtime",
                "converse",
                "--cli-input-json",
                "file://" + request_path.resolve().as_posix(),
            )
            usage = response["usage"]
            result = {
                "role": model["role"],
                "model_id": model["inference_profile"],
                "status": "passed",
                "usage": usage,
                "stop_reason": response.get("stopReason"),
                "estimated_inference_usd": str(
                    text_cost(
                        model["price_usage_prefix"], usage["inputTokens"], usage["outputTokens"]
                    )
                ),
                "response_text": "".join(
                    c.get("text", "") for c in response["output"]["message"]["content"]
                ),
            }
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            result = {
                "role": model["role"],
                "model_id": model["inference_profile"],
                "status": "failed",
                "error_type": type(exc).__name__,
            }
        results.append(result)
        print(f"{model['role']}: {result['status']}", flush=True)
        report = {
            "batch_id": batch_id,
            **identity,
            "reserved_usd": str(reservation),
            "calls": results,
            "quality_evaluation": False,
            "guardrails_tested": False,
        }
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if any(r["status"] != "passed" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
