import importlib.util
import json
import shutil
from datetime import UTC, datetime

import pytest

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.experiments import HumanReview
from incident_demo.evaluation.harness import write_new
from incident_demo.evaluation.live import (
    BASE,
    COMPARISON,
    MODEL_CENTS,
    LivePlan,
    LiveRecord,
    Review,
    Selection,
    create_plan,
    decode_result,
    export_review_packet,
    load_reviews,
    report,
    validate_plan,
)


@pytest.fixture
def mapping():
    # Synthetic mapping for structural tests; no held-out contents are inspected.
    return {f"case-{i:03}": f"{i:024x}" for i in range(1, 21)}


@pytest.fixture
def plan(root, mapping):
    return create_plan(root, "development", {"runtime_version": "test"}, mapping)


def test_full_development_grid_frozen_and_budgeted(root, mapping, plan):
    assert len(plan.trials) == 24
    assert {r.trial.case_id for r in plan.trials} == {f"case-{i:03}" for i in range(1, 9)}
    assert {r.request.settings.model for r in plan.trials} == {BASE}
    batches = {}
    for row in plan.trials:
        batches[row.request.batch_id] = batches.get(row.request.batch_id, 0) + 75
        payload = row.request.model_dump_json()
        assert row.trial.case_id not in payload
        assert "expected_facts" not in payload and "category" not in payload
    assert sum(batches.values()) == 1800 and max(batches.values()) <= 1000
    validate_plan(root, plan, {"runtime_version": "test"}, mapping)


def test_repair_grid_is_explicit_complete_and_separate_from_baseline(root, mapping, plan):
    repair = create_plan(root, "repair", {"runtime_version": "test"}, mapping, variant="V2")
    assert len(repair.trials) == 8
    assert {row.trial.variant for row in repair.trials} == {"V2"}
    assert {row.trial.case_id for row in repair.trials} == {
        row.trial.case_id for row in plan.trials
    }
    assert sum(MODEL_CENTS[row.request.settings.model] for row in repair.trials) == 600
    assert not {row.request.run_id for row in repair.trials} & {
        row.request.run_id for row in plan.trials
    }
    validate_plan(root, repair, {"runtime_version": "test"}, mapping)
    with pytest.raises(ValueError, match="explicit"):
        create_plan(root, "repair", {}, mapping)
    with pytest.raises(ValueError, match="drift"):
        validate_plan(
            root,
            repair.model_copy(update={"trials": repair.trials[:-1]}),
            {"runtime_version": "test"},
            mapping,
        )


def test_heldout_requires_selection_and_deployed_telemetry(root, mapping):
    with pytest.raises(ValueError, match="reviewed development"):
        create_plan(root, "held_out", {}, mapping)
    selection = Selection(
        variant="V1",
        model=BASE,
        reviewer_id="test-human",
        selected_at=datetime.now(UTC),
        rationale="Test only",
        development_report_sha256="0" * 64,
        comparison_report_sha256="1" * 64,
    )
    plan = create_plan(root, "held_out", {}, mapping, selection=selection)
    assert len(plan.trials) == 144
    assert sum(r.request.settings.model == BASE for r in plan.trials) == 108
    assert sum(r.request.settings.model == COMPARISON for r in plan.trials) == 36
    assert sum(MODEL_CENTS[r.request.settings.model] for r in plan.trials) == 17100
    with pytest.raises(ValueError, match="not deployed"):
        create_plan(root, "held_out", {}, {}, selection=selection)


def test_drift_and_removed_trials_rejected(root, plan, mapping):
    with pytest.raises(ValueError, match="drift"):
        validate_plan(root, plan, {"runtime_version": "changed"}, mapping)
    shortened = plan.model_copy(update={"trials": plan.trials[:-1]})
    with pytest.raises(ValueError, match="drift"):
        validate_plan(root, shortened, {"runtime_version": "test"}, mapping)


def test_duplicate_ids_rejected(plan):
    raw = plan.model_dump(mode="json")
    raw["trials"][1] = raw["trials"][0]
    with pytest.raises(ValueError, match="duplicate"):
        LivePlan.model_validate_json(json.dumps(raw))


def test_missing_and_failed_runs_remain_in_denominator(root, plan, tmp_path):
    row = plan.trials[0]
    record = LiveRecord(
        plan_sha256=content_hash(plan),
        trial_id=row.trial.trial_id,
        run_id=row.request.run_id,
        status="transport_failure",
        error_category="ReadTimeoutError",
        transport_ms=120000,
        session_stop_confirmed=False,
    )
    write_new(tmp_path / (row.trial.trial_id + ".json"), record.model_dump(mode="json"))
    result = report(root, plan, tmp_path)
    assert result["planned"] == 24 and result["recorded"] == 1
    assert result["reviewed"] == 0 and not result["release_gate_satisfied"]
    assert not result["complete"] and not result["human_review_complete"]
    assert all(r["case_success"] is False for r in result["rows"])
    assert result["usage_unknown_or_not_run"] == 24
    export_review_packet(root, plan, tmp_path, tmp_path / "packet.json")
    packet = json.loads((tmp_path / "packet.json").read_text())
    assert len(packet["entries"]) == 1
    assert packet["entries"][0]["review_template"]["review"]["facts_correct"] is None


def test_wrong_identity_and_offline_response_not_live_evidence(plan):
    row = plan.trials[0]
    base = dict(
        plan_sha256=content_hash(plan),
        trial_id=row.trial.trial_id,
        run_id=row.request.run_id,
        status="response",
        transport_ms=1,
        session_stop_confirmed=True,
    )
    assert decode_result(row, LiveRecord(**base, response={"mode": "offline_scripted"})) is None
    assert (
        decode_result(row, LiveRecord(**base, response={"mode": "aws_live", "run_id": "wrong"}))
        is None
    )


def test_reviews_bind_exact_record_and_reject_duplicate_or_unknown(tmp_path):
    review = HumanReview(
        trial_id="trial",
        reviewer_id="test-human",
        reviewed_at=datetime.now(UTC),
        facts_correct=True,
        citations_support_claims=True,
        action_appropriate=True,
        safe_output=True,
        unnecessary_tool_calls=0,
        notes="Unit test only",
    )
    raw = {"result": "one"}
    entry = Review(record_sha256=content_hash(raw), review=review).model_dump(mode="json")
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps([entry]))
    assert load_reviews(path, {"trial": raw})["trial"] == review
    for records in ({}, {"trial": {"result": "changed"}}):
        with pytest.raises(ValueError, match="stale human review"):
            load_reviews(path, records)
    path.write_text(json.dumps([entry, entry]))
    with pytest.raises(ValueError, match="duplicate"):
        load_reviews(path, {"trial": raw})


def test_source_change_requires_new_plan(root, tmp_path, mapping):
    for folder in ("src", "prompts", "knowledge", "fixtures", "evals", "infra", "scripts"):
        if folder == "infra":
            (tmp_path / folder).mkdir()
            shutil.copyfile(root / "infra/models.json", tmp_path / "infra/models.json")
        else:
            shutil.copytree(
                root / folder, tmp_path / folder, ignore=shutil.ignore_patterns("__pycache__")
            )
    shutil.copyfile(root / "uv.lock", tmp_path / "uv.lock")
    (tmp_path / "docs/evidence/p04").mkdir(parents=True)
    shutil.copyfile(
        root / "docs/evidence/p04/bedrock-prices.json",
        tmp_path / "docs/evidence/p04/bedrock-prices.json",
    )
    plan = create_plan(tmp_path, "development", {}, mapping)
    source = tmp_path / "src/incident_demo/live/adapters.py"
    source.write_text(source.read_text() + "\n# altered\n")
    with pytest.raises(ValueError, match="drift"):
        validate_plan(tmp_path, plan, {}, mapping)


@pytest.fixture
def runner_module(root):
    spec = importlib.util.spec_from_file_location(
        "p08_runner_test", root / "scripts/p08_evaluate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_interrupted_claim_recovers_without_reserving_or_invoking(
    root, plan, mapping, tmp_path, runner_module, monkeypatch
):
    calls = []

    class FakeRunner:
        package = {"development_telemetry": mapping}

        def deployment(self):
            return {"runtime_version": "test"}

        def recover(self, run_id):
            calls.append(run_id)
            return None

        def invoke(self, request, plan):
            pytest.fail("an interrupted paid attempt must not be invoked again")

    monkeypatch.setattr(runner_module, "reserve", lambda *args: pytest.fail("no new reservation"))
    row = plan.trials[0]
    write_new(tmp_path / (row.trial.trial_id + ".claim.json"), {"run_id": row.request.run_id})
    with pytest.raises(RuntimeError, match="interrupted attempt"):
        runner_module.execute_batch(root, plan, tmp_path, FakeRunner(), 1)
    record = json.loads((tmp_path / (row.trial.trial_id + ".json")).read_text())
    assert record["status"] == "unknown" and calls == [row.request.run_id]
    assert not (tmp_path / ".runner.lock").exists()


def test_transport_failure_retains_reservation_and_stops_batch(
    root, plan, mapping, tmp_path, runner_module, monkeypatch
):
    reservations, invocations = [], []

    class FakeRunner:
        package = {"development_telemetry": mapping}

        def deployment(self):
            return {"runtime_version": "test"}

        def invoke(self, request, plan):
            invocations.append(request.run_id)
            return None, "ReadTimeoutError", True, 150000

    monkeypatch.setattr(runner_module, "reserve", lambda *args: reservations.append(args))
    with pytest.raises(RuntimeError, match="incomplete usage/transport"):
        runner_module.execute_batch(root, plan, tmp_path, FakeRunner(), 12)
    assert len(reservations) == len(invocations) == 1
    record = json.loads((tmp_path / (plan.trials[0].trial.trial_id + ".json")).read_text())
    assert record["status"] == "transport_failure"
    assert not (tmp_path / ".runner.lock").exists()
