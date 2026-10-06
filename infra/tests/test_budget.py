import json
from decimal import Decimal

import pytest

from budget import estimate, reserve, text_cost
from deployment_policy import policy
from settings import load_config


def test_cost_uses_input_and_output_rates():
    assert text_cost("USE2-NovaPro", 6000, 1500) == Decimal("0.0096")
    assert estimate()["model_total_usd"] == "2.6049600000"


def test_total_and_batch_limits_and_duplicate_reservation(tmp_path):
    path = tmp_path / "ledger.json"
    for n in range(4):
        reserve(str(n), Decimal("10"), path)
    for name, amount in [("4", "0.01"), ("0", "1"), ("5", "11"), ("6", "-1"), ("7", "NaN")]:
        with pytest.raises(ValueError):
            reserve(name, Decimal(amount), path)
    assert len(json.loads(path.read_text())["reservations"]) == 4


def test_competing_process_cannot_overwrite_ledger(tmp_path):
    path = tmp_path / "ledger.json"
    path.with_suffix(".lock").touch()
    with pytest.raises(FileExistsError):
        reserve("a", Decimal("1"), path)
    assert not path.exists()


def test_deployment_policy_cannot_manage_roles_or_other_tables():
    statements = policy(load_config())["Statement"]
    for statement in statements:
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        assert all(not a.startswith(("iam:", "organizations:", "bedrock:")) for a in actions)
        assert all(not a.endswith(":*") for a in actions)
        if statement["Resource"] == "*":
            assert actions == [
                "logs:DescribeLogGroups",
                "logs:DescribeIndexPolicies",
                "logs:DescribeResourcePolicies",
            ]
        if any(a.startswith("dynamodb:") for a in actions):
            assert statement["Resource"].endswith(":table/incident-demo-state")
