"""Load agent-safe fixtures separately from evaluator-only case expectations."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from incident_demo.contracts.base import Contract, Digest, Identifier, ServiceId, Text, Timestamp
from incident_demo.contracts.records import Evidence
from incident_demo.contracts.tools import Passage

CaseId = Annotated[str, Field(pattern=r"^case-[0-9]{3}$")]
CorpusPath = Annotated[
    str, Field(pattern=r"^(fixtures/cases/case-[0-9]{3}\.json|knowledge/[a-z0-9-]+\.md)$")
]


class IncidentInput(Contract):
    service_id: ServiceId
    submitted_at: Timestamp
    summary: Text


class ToolError(Contract):
    status: Literal["error"]
    source: Literal["get_service_health", "get_recent_changes", "get_recent_logs"]
    code: Literal["transient_unavailable", "persistent_unavailable"]
    retryable: bool


class ToolSuccess(Contract):
    status: Literal["ok"]
    evidence: Evidence


ToolResponse = Annotated[ToolSuccess | ToolError, Field(discriminator="status")]


class Fixture(Contract):
    """No split, expected action, diagnosis, scenario name or scoring labels."""

    schema_version: Literal["1.0.0"]
    fixture_version: Literal["1.0.0"]
    incident: IncidentInput
    responses: Annotated[tuple[ToolResponse, ...], Field(min_length=1, max_length=8)]
    retrieval_passage_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=5)]


class Case(Contract):
    case_id: CaseId
    split: Literal["development", "held_out"]
    category: Literal[
        "actionable",
        "dependency",
        "missing_evidence",
        "conflicting_evidence",
        "injection",
        "stale_data",
        "tool_failure",
    ]
    fixture_path: CorpusPath
    fixture_sha256: Digest
    expected_facts: Annotated[tuple[Text, ...], Field(min_length=1)]
    acceptable_outcomes: Annotated[
        tuple[Literal["propose_rollback", "escalate", "incomplete"], ...], Field(min_length=1)
    ]
    forbidden_claims: Annotated[tuple[Text, ...], Field(min_length=1)]
    required_evidence_ids: tuple[Identifier, ...]
    rationale: Text


class RunbookEntry(Contract):
    path: CorpusPath
    sha256: Digest
    passage: Passage


class KnowledgeCatalog(Contract):
    corpus_version: Literal["1.0.0"]
    documents: Annotated[tuple[RunbookEntry, ...], Field(min_length=8, max_length=8)]


class Manifest(Contract):
    manifest_version: Literal["1.0.0"]
    frozen_at: Timestamp
    corpus_version: Literal["1.0.0"]
    knowledge_catalog_sha256: Digest
    cases: Annotated[tuple[Case, ...], Field(min_length=20, max_length=20)]

    @model_validator(mode="after")
    def check_split(self) -> Self:
        if len({case.case_id for case in self.cases}) != 20:
            raise ValueError("case IDs must be unique")
        if sum(case.split == "development" for case in self.cases) != 8:
            raise ValueError("require eight development and twelve held-out cases")
        if any(case.fixture_path != f"fixtures/cases/{case.case_id}.json" for case in self.cases):
            raise ValueError("fixture path must match case ID")
        return self


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_fixture(path: Path) -> Fixture:
    """This loader never reads the evaluation manifest."""
    return Fixture.model_validate_json(path.read_bytes())


def load_knowledge(root: Path) -> KnowledgeCatalog:
    return KnowledgeCatalog.model_validate_json((root / "knowledge/catalog.json").read_bytes())


def validate_corpus(root: Path) -> dict[str, int]:
    """Evaluator/CI command only; do not expose its manifest to an investigator."""
    manifest_path = root / "evals/case-manifest.json"
    frozen_digest = (root / "evals/case-manifest.sha256").read_text().strip()
    if sha256_file(manifest_path) != frozen_digest:
        raise ValueError("frozen manifest changed; version changes must be explicit")
    manifest = Manifest.model_validate_json(manifest_path.read_bytes())
    if sha256_file(root / "knowledge/catalog.json") != manifest.knowledge_catalog_sha256:
        raise ValueError("knowledge catalog hash mismatch")
    catalog = load_knowledge(root)
    passages = {entry.passage.passage_id for entry in catalog.documents}
    documents = {entry.passage.document_id for entry in catalog.documents}
    if len(passages) != 8 or len(documents) != 8:
        raise ValueError("duplicate runbook passage/document IDs")
    for entry in catalog.documents:
        path = root / entry.path
        if not entry.path.startswith("knowledge/") or sha256_file(path) != entry.sha256:
            raise ValueError(f"runbook hash mismatch: {entry.path}")
        if path.read_text(encoding="utf-8") != entry.passage.excerpt:
            raise ValueError(f"runbook excerpt mismatch: {entry.path}")
    for case in manifest.cases:
        path = root / case.fixture_path
        if sha256_file(path) != case.fixture_sha256:
            raise ValueError(f"fixture hash mismatch: {case.case_id}")
        fixture = load_fixture(path)
        available = [r.evidence.evidence_id for r in fixture.responses if r.status == "ok"]
        if len(available) != len(set(available)):
            raise ValueError(f"duplicate evidence IDs: {case.case_id}")
        if set(fixture.retrieval_passage_ids) - passages:
            raise ValueError(f"unknown runbook passage: {case.case_id}")
        if set(case.required_evidence_ids) - set(available) - set(fixture.retrieval_passage_ids):
            raise ValueError(f"unknown expected evidence: {case.case_id}")
    return {"development": 8, "held_out": 12, "runbooks": len(catalog.documents)}


def json_document(value: dict) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"
