"""Conservative local reservations. This is not an account-wide AWS billing cap."""

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from settings import ROOT, load_config

PRICES = ROOT.parent / "docs/evidence/p04/bedrock-prices.json"
LEDGER = ROOT.parent / "runs/p04-budget-ledger.json"


def rates() -> dict[str, Decimal]:
    snapshot = json.loads(PRICES.read_text(encoding="utf-8-sig"))
    if any(row["unit"] != "1K tokens" for row in snapshot["rates"]):
        raise ValueError("unsupported price unit")
    return {row["usage"]: Decimal(row["usd"]) / 1000 for row in snapshot["rates"]}


def text_cost(prefix: str, input_tokens: int, output_tokens: int) -> Decimal:
    if min(input_tokens, output_tokens) < 0:
        raise ValueError("token counts must be nonnegative")
    prices = rates()
    return (
        prices[f"{prefix}-input-tokens"] * input_tokens
        + prices[f"{prefix}-output-tokens"] * output_tokens
    )


def reserve(batch_id: str, amount: Decimal, path: Path = LEDGER):
    """Keep the full reservation after failures or unknown billing; never auto-release it."""
    config = load_config()["budget"]
    if not amount.is_finite() or not 0 < amount <= Decimal(str(config["per_batch"])):
        raise ValueError("reservation outside approved batch budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    # Exclusive creation prevents lost updates between local smoke processes.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(fd)
        data = json.loads(path.read_text()) if path.exists() else {"reservations": []}
        if any(r["batch_id"] == batch_id for r in data["reservations"]):
            raise ValueError("batch already reserved")
        used = sum((Decimal(r["reserved_usd"]) for r in data["reservations"]), Decimal(0))
        capacity = Decimal(str(config["total"])) - Decimal(str(config["infrastructure_reserve"]))
        if used + amount > capacity:
            raise ValueError("total model allowance exhausted; infrastructure reserve is protected")
        data["reservations"].append(
            {
                "batch_id": batch_id,
                "reserved_usd": str(amount),
                "reserved_at": datetime.now(UTC).isoformat(),
            }
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        lock.unlink()


def estimate() -> dict:
    limits = load_config()["limits"]
    models = json.loads((ROOT / "models.json").read_text())["text"]
    calls = {
        "base": 108 * limits["model_calls_per_investigation"],
        "comparison": 36 * limits["model_calls_per_investigation"],
        "judge": 12,
    }
    costs = {
        model["role"]: text_cost(
            model["price_usage_prefix"],
            limits["input_tokens_per_call"],
            limits["output_tokens_per_call"],
        )
        * calls[model["role"]]
        for model in models
    }
    return {
        "assumptions": limits,
        "calls": calls,
        "model_upper_estimates_usd": {k: str(v) for k, v in costs.items()},
        "model_total_usd": str(sum(costs.values())),
        "excludes": [
            "development",
            "retrieval",
            "guardrails",
            "runtime",
            "storage",
            "logging",
            "tax",
        ],
        "note": "A planning estimate, not permission to run P08 or a measured bill.",
    }


if __name__ == "__main__":
    print(json.dumps(estimate(), indent=2))
