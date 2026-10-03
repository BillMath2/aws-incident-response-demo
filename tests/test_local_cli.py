import json
import shutil
import subprocess
import sys

import pytest

from incident_demo.contracts.local import LocalRunRecord
from incident_demo.local_cli import run_demo


def cli(root, output, *args, stdin=""):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "incident_demo.cli",
            "--root",
            str(root),
            "demo",
            "--output",
            str(output),
            *args,
        ],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize(
    "decision,profile,state,revision",
    [
        ("approve", "recovered", "resolved", 1),
        ("approve", "unhealthy", "unresolved", 1),
        ("approve", "missing", "unresolved", 1),
        ("reject", "recovered", "rejected", 0),
        ("pending", "recovered", "awaiting_approval", 0),
    ],
)
def test_scripted_walkthrough(root, tmp_path, decision, profile, state, revision):
    output = tmp_path / "run.json"
    result = cli(root, output, "--decision", decision, "--verification", profile)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LOCAL STUB" in result.stdout
    assert "Exact proposal for review" in result.stdout
    record = LocalRunRecord.model_validate_json(output.read_bytes())
    assert record.run.state == state
    assert record.service.revision == revision


def test_eof_is_not_approval(root, tmp_path):
    output = tmp_path / "run.json"
    result = cli(root, output)
    assert result.returncode == 0
    record = LocalRunRecord.model_validate_json(output.read_bytes())
    assert record.approval is None
    assert record.service.revision == 0


def test_wrong_hash_is_not_approval(root, tmp_path):
    output = tmp_path / "run.json"
    result = cli(root, output, stdin="approve\nwrong-hash\n")
    assert result.returncode == 2
    record = LocalRunRecord.model_validate_json(output.read_bytes())
    assert record.approval is None
    assert record.service.revision == 0


def test_wrong_actor_and_existing_export_are_refused(root, tmp_path):
    output = tmp_path / "run.json"
    result = cli(root, output, "--decision", "approve", "--actor", "local-investigator")
    assert result.returncode == 2
    before = output.read_bytes()
    assert json.loads(before)["service"]["revision"] == 0
    assert cli(root, output, "--decision", "approve").returncode == 1
    assert output.read_bytes() == before


def test_walkthrough_does_not_require_evaluator_files(root, tmp_path):
    for folder in ("fixtures", "knowledge"):
        shutil.copytree(root / folder, tmp_path / folder)
    result = cli(tmp_path, tmp_path / "run.json", "--decision", "approve")
    assert result.returncode == 0, result.stderr
    assert "Final state: resolved" in result.stdout
    assert not (tmp_path / "evals").exists()


def test_observer_failure_leaves_unresolved_export(root, tmp_path):
    for folder in ("fixtures", "knowledge"):
        shutil.copytree(root / folder, tmp_path / folder)
    (tmp_path / "fixtures/local-verification.json").write_text("invalid json")
    result = cli(tmp_path, tmp_path / "run.json", "--decision", "approve")
    assert result.returncode == 2
    assert json.loads((tmp_path / "run.json").read_text())["run"]["state"] == "unresolved"


def test_interactive_review_requires_displayed_hash(root, tmp_path, monkeypatch, capsys):
    from argparse import Namespace

    args = Namespace(
        root=root,
        case="case-001",
        decision=None,
        actor="local-approver",
        reason="Manual review",
        verification="recovered",
        output=tmp_path / "run.json",
    )

    def answer(prompt):
        if "Decision" in prompt:
            return "approve"
        text = capsys.readouterr().out
        proposal_text = text.split("Exact proposal for review:\n", 1)[1]
        return json.loads(proposal_text)["proposal_hash"]

    monkeypatch.setattr("builtins.input", answer)
    assert run_demo(args) == 0
    record = LocalRunRecord.model_validate_json(args.output.read_bytes())
    assert record.run.state == "resolved"
