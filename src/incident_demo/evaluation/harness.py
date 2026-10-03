"""Freeze, execute and report offline development trials without leaking evaluator labels."""

import json
from datetime import UTC, datetime
from pathlib import Path

from incident_demo.contracts.base import Contract, content_hash
from incident_demo.contracts.experiments import (
    ExperimentResult,
    HumanReview,
    Score,
    Settings,
    Trial,
    TrialManifest,
)
from incident_demo.corpus import (
    Manifest,
    json_document,
    load_fixture,
    load_knowledge,
    sha256_file,
    validate_corpus,
)
from incident_demo.evaluation.scoring import score, summarize
from incident_demo.investigator.engine import Engine
from incident_demo.investigator.providers import FixtureTools, OfflineProvider

PROMPT_FILES = ("shared-v1.txt", "v0-v1.txt", "v1-v1.txt", "v2-v1.txt")


class TrialRecord(Contract):
    trial: Trial
    result: ExperimentResult
    score: Score


def prompt_manifest(root: Path) -> dict:
    return {
        "version": "1.0.0",
        "shared_output_contract": "Investigation",
        "files": {name: sha256_file(root / "prompts" / name) for name in PROMPT_FILES},
        "variants": {"V0": "v0-v1.txt", "V1": "v1-v1.txt", "V2": "v2-v1.txt"},
    }


def check_prompts(root: Path):
    stored = json.loads((root / "prompts/manifest.json").read_text(encoding="utf-8"))
    if stored != prompt_manifest(root):
        raise ValueError("prompt manifest drift; review and version changed prompts explicitly")


def source_hash(root: Path) -> str:
    return content_hash(
        {
            p.relative_to(root).as_posix(): sha256_file(p)
            for p in sorted((root / "src").rglob("*.py"))
        }
    )


def development_cases(root: Path):
    validate_corpus(root)
    manifest = Manifest.model_validate_json((root / "evals/case-manifest.json").read_bytes())
    return {c.case_id: c for c in manifest.cases if c.split == "development"}


def build_trials(cases, repetitions):
    return tuple(
        Trial(
            trial_id=f"dev-{case}-{variant.lower()}-r{repeat}",
            case_id=case,
            variant=variant,
            repetition=repeat,
        )
        for case in sorted(cases)
        for variant in ("V0", "V1", "V2")
        for repeat in range(1, repetitions + 1)
    )


def create_manifest(root: Path, repetitions: int = 1, settings: Settings | None = None):
    if repetitions not in (1, 2, 3):
        raise ValueError("repetitions must be between one and three")
    check_prompts(root)
    cases = development_cases(root)
    return TrialManifest(
        created_at=datetime.now(UTC),
        settings=settings if settings is not None else Settings(),
        corpus_sha256=sha256_file(root / "evals/case-manifest.json"),
        prompts_sha256=sha256_file(root / "prompts/manifest.json"),
        rubric_sha256=sha256_file(root / "evals/rubric-v1.json"),
        source_sha256=source_hash(root),
        lock_sha256=sha256_file(root / "uv.lock"),
        trials=build_trials(cases, repetitions),
    )


def validate_manifest(root: Path, manifest: TrialManifest):
    current = create_manifest(root, max(t.repetition for t in manifest.trials), manifest.settings)
    if manifest.model_dump(exclude={"created_at"}) != current.model_dump(exclude={"created_at"}):
        raise ValueError("trial configuration, code, corpus, prompt, dependency or rubric drift")


def write_new(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json_document(data))


def run_trials(root: Path, manifest: TrialManifest, output: Path):
    validate_manifest(root, manifest)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "manifest.json", manifest.model_dump(mode="json"))
    cases = development_cases(root)
    rows = []
    for trial in manifest.trials:
        # Fresh adapters and graph per trial. No approval/executor is instantiated.
        fixture = load_fixture(root / cases[trial.case_id].fixture_path)
        tools = FixtureTools(fixture, load_knowledge(root))
        result = Engine(
            root, trial.variant, fixture.incident, OfflineProvider(), tools, manifest.settings
        ).run()
        row = TrialRecord(
            trial=trial, result=result, score=score(trial, result, cases[trial.case_id])
        )
        rows.append(row)
        write_new(output / f"{trial.trial_id}.json", row.model_dump(mode="json"))
    report = summarize(rows, manifest, cases)
    write_new(output / "report.json", report)
    artifacts = {p.name: sha256_file(p) for p in sorted(output.glob("*.json"))}
    write_new(output / "artifacts.json", {"sha256": artifacts})
    return report


def report_trials(root: Path, directory: Path, review_path: Path | None = None):
    artifacts = json.loads((directory / "artifacts.json").read_text(encoding="utf-8"))["sha256"]
    # Restrict the manifest's artifact paths before opening anything selected by it.
    if any(Path(name).name != name or ":" in name or "\\" in name for name in artifacts):
        raise ValueError("invalid artifact filename")
    if any(sha256_file(directory / name) != digest for name, digest in artifacts.items()):
        raise ValueError("retained trial artifact hash mismatch")
    manifest = TrialManifest.model_validate_json((directory / "manifest.json").read_bytes())
    # Reporting old evidence does not require today's source tree, but must use its frozen cases.
    if manifest.corpus_sha256 != sha256_file(root / "evals/case-manifest.json"):
        raise ValueError("report needs the original frozen case manifest")
    if manifest.rubric_sha256 != sha256_file(root / "evals/rubric-v1.json"):
        raise ValueError("report needs the original scoring rubric")
    cases = development_cases(root)
    if manifest.trials != build_trials(cases, max(t.repetition for t in manifest.trials)):
        raise ValueError("unexpected trial grid")
    required = {"manifest.json", "report.json"} | {f"{t.trial_id}.json" for t in manifest.trials}
    if set(artifacts) != required:
        raise ValueError("artifact manifest must include every planned trial")
    reviews = {}
    if review_path:
        entries = json.loads(review_path.read_text(encoding="utf-8"))
        for entry in entries:
            review = HumanReview.model_validate_json(json.dumps(entry))
            if review.trial_id in reviews or review.trial_id not in {
                t.trial_id for t in manifest.trials
            }:
                raise ValueError("duplicate or unknown human review")
            reviews[review.trial_id] = review
    rows = []
    for trial in manifest.trials:
        stored = TrialRecord.model_validate_json(
            (directory / f"{trial.trial_id}.json").read_bytes()
        )
        if stored.trial != trial or stored.result.variant != trial.variant:
            raise ValueError("trial/result identity mismatch")
        rows.append(
            TrialRecord(
                trial=trial,
                result=stored.result,
                score=score(
                    trial, stored.result, cases[trial.case_id], reviews.get(trial.trial_id)
                ),
            )
        )
    report = summarize(rows, manifest, cases)
    report["original_source_sha256"] = manifest.source_sha256
    report["reporting_source_sha256"] = source_hash(root)
    report["human_review_file_sha256"] = sha256_file(review_path) if review_path else None
    report["reviewed_scores"] = [row.score.model_dump(mode="json") for row in rows]
    report["human_reviews"] = [r.model_dump(mode="json") for r in reviews.values()]
    return report
