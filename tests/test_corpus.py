import json
import shutil
from collections import Counter

import pytest
from pydantic import ValidationError

from incident_demo.cli import export_schemas
from incident_demo.corpus import Fixture, Manifest, load_fixture, load_knowledge, validate_corpus


def test_frozen_corpus_and_schemas(root):
    assert validate_corpus(root) == {"development": 8, "held_out": 12, "runbooks": 8}
    export_schemas(root, check=True)


def test_held_out_composition_and_versioned_knowledge(root):
    manifest = Manifest.model_validate_json((root / "evals/case-manifest.json").read_bytes())
    assert Counter(c.category for c in manifest.cases if c.split == "held_out") == {
        "actionable": 4,
        "dependency": 1,
        "missing_evidence": 1,
        "conflicting_evidence": 1,
        "injection": 3,
        "stale_data": 1,
        "tool_failure": 1,
    }
    catalog = load_knowledge(root)
    assert Counter(e.passage.status for e in catalog.documents) == {
        "current": 6,
        "stale": 1,
        "conflicting": 1,
    }


def test_fixture_loader_operates_without_answer_keys(root, tmp_path):
    target = tmp_path / "fixture.json"
    shutil.copyfile(root / "fixtures/cases/case-001.json", target)
    assert load_fixture(target).incident.service_id == "checkout-api"
    assert not (tmp_path / "evals").exists()


@pytest.mark.parametrize(
    "field", ["split", "category", "expected_facts", "acceptable_outcomes", "scenario"]
)
def test_fixtures_reject_evaluator_metadata(root, field):
    data = json.loads((root / "fixtures/cases/case-001.json").read_text())
    data[field] = "leaked answer key"
    with pytest.raises(ValidationError):
        Fixture.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "path",
    [
        "fixtures/cases/case-001.json",
        "knowledge/rollback.md",
        "evals/case-manifest.json",
    ],
)
def test_corpus_detects_content_drift(root, tmp_path, path):
    for folder in ("fixtures", "knowledge", "evals"):
        shutil.copytree(root / folder, tmp_path / folder)
    with (tmp_path / path).open("a", encoding="utf-8") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="hash mismatch|frozen manifest changed"):
        validate_corpus(tmp_path)


def test_manifest_rejects_duplicate_cases_wrong_split_and_escaping_path(root):
    data = json.loads((root / "evals/case-manifest.json").read_text())
    data["cases"][0]["fixture_path"] = "../../private.json"
    with pytest.raises(ValidationError):
        Manifest.model_validate_json(json.dumps(data))
    data = json.loads((root / "evals/case-manifest.json").read_text())
    data["cases"][0] = data["cases"][1]
    with pytest.raises(ValidationError, match="unique"):
        Manifest.model_validate_json(json.dumps(data))
    data = json.loads((root / "evals/case-manifest.json").read_text())
    data["cases"][0]["split"] = "held_out"
    with pytest.raises(ValidationError, match="eight development"):
        Manifest.model_validate_json(json.dumps(data))
