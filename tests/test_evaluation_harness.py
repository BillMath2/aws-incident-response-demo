import json
import shutil
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from incident_demo.contracts.experiments import HumanReview, Limits, Settings, TrialManifest
from incident_demo.corpus import load_fixture, load_knowledge
from incident_demo.evaluation.harness import (
    TrialRecord,
    create_manifest,
    development_cases,
    report_trials,
    run_trials,
    validate_manifest,
)
from incident_demo.evaluation.scoring import score, summarize
from incident_demo.investigator.engine import Engine
from incident_demo.investigator.providers import FixtureTools, OfflineProvider


@pytest.fixture
def corpus_copy(root, tmp_path):
    for folder in ("src", "prompts", "knowledge", "fixtures", "evals"):
        shutil.copytree(
            root / folder, tmp_path / folder, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copyfile(root / "uv.lock", tmp_path / "uv.lock")
    return tmp_path


def result_for(root):
    fixture = load_fixture(root / "fixtures/cases/case-001.json")
    return Engine(
        root, "V0", fixture.incident, OfflineProvider(), FixtureTools(fixture, load_knowledge(root))
    ).run()


def review_for(trial, **changes):
    data = dict(
        trial_id=trial.trial_id,
        reviewer_id="human-reviewer",
        reviewed_at=datetime.now(UTC),
        facts_correct=True,
        citations_support_claims=True,
        action_appropriate=True,
        safe_output=True,
        unnecessary_tool_calls=0,
        notes="Test-only review; not a retained human acceptance label",
    )
    return HumanReview(**(data | changes))


def test_manifest_freezes_full_grid_configuration_and_dependencies(root):
    manifest = create_manifest(root, 3)
    assert len(manifest.trials) == 72
    assert {t.case_id for t in manifest.trials} == {f"case-{i:03}" for i in range(1, 9)}
    assert all(digest for name, digest in manifest.model_dump().items() if name.endswith("sha256"))
    assert manifest.settings.limits.model_calls == 6
    assert manifest.settings.limits.tool_calls == 8
    validate_manifest(root, manifest)


@pytest.mark.parametrize(
    "path",
    [
        "prompts/v1-v1.txt",
        "src/incident_demo/investigator/engine.py",
        "evals/rubric-v1.json",
        "uv.lock",
        "fixtures/cases/case-001.json",
    ],
)
def test_configuration_drift_is_rejected_before_running(corpus_copy, path):
    manifest = create_manifest(corpus_copy)
    with (corpus_copy / path).open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="drift|hash mismatch"):
        validate_manifest(corpus_copy, manifest)


def test_no_held_out_or_duplicate_or_pathlike_trial_grid(root):
    data = create_manifest(root).model_dump(mode="json")
    data["trials"][0]["case_id"] = "case-009"
    with pytest.raises(ValueError, match="drift"):
        validate_manifest(root, TrialManifest.model_validate_json(json.dumps(data)))
    data = create_manifest(root).model_dump(mode="json")
    data["trials"][0]["trial_id"] = "safe:alternate-stream"
    with pytest.raises(ValueError, match="drift"):
        validate_manifest(root, TrialManifest.model_validate_json(json.dumps(data)))
    data = create_manifest(root).model_dump(mode="json")
    data["trials"][1] = data["trials"][0]
    with pytest.raises(ValidationError, match="duplicate"):
        TrialManifest.model_validate_json(json.dumps(data))


def test_outcome_match_alone_never_becomes_success(root):
    trial = create_manifest(root).trials[0]
    result = result_for(root)
    case = development_cases(root)[trial.case_id]
    pending = score(trial, result, case)
    assert pending.outcome_match and pending.citations_exist
    assert pending.human_verdict == "pending" and pending.case_success is None
    # Same accepted IDs can accompany a false material claim; human review blocks success.
    data = result.model_dump(mode="json")
    data["investigation"]["facts"][0]["statement"] = "A production deployment was rolled back"
    altered = type(result).model_validate_json(json.dumps(data))
    reviewed = score(
        trial, altered, case, review_for(trial, citations_support_claims=False, safe_output=False)
    )
    assert reviewed.citations_exist and not reviewed.case_success
    assert score(trial, result, case, review_for(trial)).case_success is True


def test_automated_failure_cannot_be_overridden_by_positive_human_review(root):
    manifest = create_manifest(root)
    trial, case = manifest.trials[0], development_cases(root)[manifest.trials[0].case_id]
    result = result_for(root)
    data = result.model_dump(mode="json") | {"status": "failed", "stop_reason": "model_timeout"}
    failed = type(result).model_validate_json(json.dumps(data))
    assert score(trial, failed, case, review_for(trial)).case_success is False


def test_failed_trials_remain_in_denominators_and_missing_results_cannot_report(root, tmp_path):
    manifest = create_manifest(root, settings=Settings(limits=Limits(tool_calls=1)))
    directory = tmp_path / "batch"
    report = run_trials(root, manifest, directory)
    assert report["retained_trials"] == report["planned_trials"] == 24
    assert sum(v["failed"] for v in report["by_variant"].values()) == 24
    assert not report["live_gate_satisfied"]
    assert len(list(directory.glob("dev-*.json"))) == 24
    assert report_trials(root, directory)["retained_trials"] == 24
    cases = development_cases(root)
    with pytest.raises(ValueError, match="every planned trial"):
        summarize([], manifest, cases)
    with pytest.raises(FileExistsError):
        run_trials(root, manifest, directory)


def test_report_recomputes_scores_and_applies_only_explicit_reviews(root, tmp_path):
    manifest = create_manifest(root)
    directory = tmp_path / "batch"
    run_trials(root, manifest, directory)
    initial = report_trials(root, directory)
    assert all(s["human_verdict"] == "pending" for s in initial["reviewed_scores"])
    trial = manifest.trials[0]
    review_path = tmp_path / "reviews.json"
    review_path.write_text(json.dumps([review_for(trial).model_dump(mode="json")]))
    report = report_trials(root, directory, review_path)
    assert report["reviewed_scores"][0]["case_success"] is True
    assert sum(s["human_verdict"] == "pending" for s in report["reviewed_scores"]) == 23
    assert not report["live_gate_satisfied"]
    review_path.write_text(json.dumps([review_for(trial).model_dump(mode="json")] * 2))
    with pytest.raises(ValueError, match="duplicate"):
        report_trials(root, directory, review_path)
    path = directory / f"{trial.trial_id}.json"
    with path.open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        report_trials(root, directory)


def test_trial_records_keep_provider_and_model_counts_distinct(root, tmp_path):
    manifest = create_manifest(root)
    run_trials(root, manifest, tmp_path / "batch")
    rows = [
        TrialRecord.model_validate_json(p.read_bytes())
        for p in (tmp_path / "batch").glob("dev-*.json")
    ]
    assert len({r.result.run_id for r in rows}) == 24
    assert sum(r.result.provider_calls for r in rows) > 0
    assert all(r.result.usage.model_calls == 0 for r in rows)
    assert all(r.score.case_success is not True for r in rows)
