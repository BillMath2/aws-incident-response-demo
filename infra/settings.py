"""Explicit deployment target; never infer a target from ambient credentials."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_config(path: Path = ROOT / "config.json") -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9]{12}", config["account"]):
        raise ValueError("a literal 12-digit account is required")
    if config["region"] != "us-east-2":
        raise ValueError("this readiness baseline is verified only for us-east-2")
    if config["project"] != "incident-demo" or config["stack_name"] != "incident-demo-foundation":
        raise ValueError("resource names must match the scoped execution policy")
    budget = config["budget"]
    if not 0 < budget["per_batch"] <= budget["total"] <= 50:
        raise ValueError("budget exceeds the approved $50 total / $10 batch allowance")
    if budget["per_batch"] > 10 or not 0 < budget["infrastructure_reserve"] < budget["total"]:
        raise ValueError("invalid batch limit or infrastructure reserve")
    return config
