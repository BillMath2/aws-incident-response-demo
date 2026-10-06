"""Retain read-only readiness evidence; never equate an API list with a live service test."""

import argparse
import json
import subprocess
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
    models = json.loads((ROOT / "models.json").read_text())
    checks = {
        "cloudformation": ("cloudformation", "list-stacks", "--query", "length(StackSummaries)"),
        "agentcore": (
            "bedrock-agentcore-control",
            "list-agent-runtimes",
            "--query",
            "length(agentRuntimes)",
        ),
        "knowledge_bases": (
            "bedrock-agent",
            "list-knowledge-bases",
            "--query",
            "length(knowledgeBaseSummaries)",
        ),
        "guardrails": ("bedrock", "list-guardrails", "--query", "length(guardrails)"),
        "vector_buckets": ("s3vectors", "list-vector-buckets", "--query", "length(vectorBuckets)"),
    }
    for model in models["text"]:
        checks[f"availability_{model['role']}"] = (
            "bedrock",
            "get-foundation-model-availability",
            "--model-id",
            model["foundation_model"],
        )
        checks[f"profile_{model['role']}"] = (
            "bedrock",
            "get-inference-profile",
            "--inference-profile-identifier",
            model["inference_profile"],
            "--query",
            "{status:status,models:models}",
        )
    checks["availability_embedding"] = (
        "bedrock",
        "get-foundation-model-availability",
        "--model-id",
        models["retrieval"]["embedding_model"],
    )
    results = {}
    for name, command in checks.items():
        try:
            response = aws(config, *command)
            ready = True
            if name.startswith("availability_"):
                ready = (
                    response.get("authorizationStatus") == "AUTHORIZED"
                    and response.get("regionAvailability") == "AVAILABLE"
                    and response.get("entitlementAvailability") == "AVAILABLE"
                    and response.get("agreementAvailability", {}).get("status") == "AVAILABLE"
                )
            elif name.startswith("profile_"):
                ready = response.get("status") == "ACTIVE"
            results[name] = {"status": "passed" if ready else "unavailable", "response": response}
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            results[name] = {"status": "failed", "error_type": type(exc).__name__}
        print(f"{name}: {results[name]['status']}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                **identity,
                "checks": results,
                "inference_tested": False,
            },
            stream,
            indent=2,
        )
        stream.write("\n")
    if any(r["status"] != "passed" for r in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
