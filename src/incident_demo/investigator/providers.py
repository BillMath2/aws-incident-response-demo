"""Provider seam and offline scripted implementation. No network calls or evaluator data."""

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.experiments import Branch, Candidate, ChooseTool, Finish, SearchReply
from incident_demo.contracts.records import Evidence
from incident_demo.contracts.tools import CALL_ADAPTER
from incident_demo.corpus import Fixture, IncidentInput, KnowledgeCatalog
from incident_demo.investigator.stub import investigate
from incident_demo.local_tools import sanitized_evidence


class TransientFailure(Exception):
    """An operation may be retried once within its global budget."""


class ToolFailure(Exception):
    """A required diagnostic or retrieval could not complete."""


@dataclass(frozen=True)
class ModelRequest:
    run_id: str
    variant: str
    phase: str
    round: int
    incident: IncidentInput
    evidence: tuple[Evidence, ...]
    branches: tuple[Branch, ...]
    system_prompt: str
    response_schema: dict
    tool_schema: dict
    remaining_model_calls: int
    remaining_tool_calls: int
    max_output_tokens: int
    temperature: float


class Provider(Protocol):
    def respond(self, request: ModelRequest, *, timeout_seconds: float) -> str: ...


def tool_call(name: str):
    arguments = {"service_id": "checkout-api"}
    if name == "retrieve_runbook":
        arguments.update(query="checkout rollback policy", limit=5)
    return CALL_ADAPTER.validate_python({"name": name, "arguments": arguments})


class FixtureTools:
    """Fresh adapter per run. Arguments constrain fixture responses; no arbitrary I/O."""

    def __init__(self, fixture: Fixture, catalog: KnowledgeCatalog):
        self.fixture, self.catalog = fixture, catalog
        self.offsets: dict[str, int] = {}

    def invoke(self, call, *, timeout_seconds: float) -> tuple[Evidence, ...]:
        call = CALL_ADAPTER.validate_json(call.model_dump_json())
        if timeout_seconds <= 0:
            raise TimeoutError()
        if call.name == "retrieve_runbook":
            lookup = {entry.passage.passage_id: entry.passage for entry in self.catalog.documents}
            ids = self.fixture.retrieval_passage_ids[: call.arguments.limit]
            if any(key not in lookup for key in ids):
                raise ToolFailure()
            return tuple(
                sanitized_evidence(
                    Evidence(
                        evidence_id=key,
                        source="retrieve_runbook",
                        source_version=lookup[key].version,
                        collected_at=self.fixture.incident.submitted_at,
                        complete=True,
                        sanitized=True,
                        payload=lookup[key],
                        content_hash=content_hash(lookup[key]),
                    )
                )
                for key in ids
            )
        responses = [
            r
            for r in self.fixture.responses
            if (r.source if r.status == "error" else r.evidence.source) == call.name
        ]
        offset = self.offsets.get(call.name, 0)
        self.offsets[call.name] = offset + 1
        # Repeated reads after a successful fixture observation return the immutable observation.
        response = responses[min(offset, len(responses) - 1)] if responses else None
        if response is None:
            raise ToolFailure()
        if response.status == "error":
            if response.retryable:
                raise TransientFailure()
            raise ToolFailure()
        evidence = sanitized_evidence(response.evidence)
        # Avoid pretending a fixture supports server-side filtering it does not implement.
        if call.name == "get_recent_logs":
            if (
                call.arguments.filter != "errors"
                or len(evidence.payload.entries) > call.arguments.limit
            ):
                raise ToolFailure()
        if call.name == "get_recent_changes":
            oldest = self.fixture.incident.submitted_at - timedelta(
                minutes=call.arguments.window_minutes
            )
            if any(change.changed_at < oldest for change in evidence.payload.items):
                raise ToolFailure()
        return (evidence,)


class OfflineBoundaryPolicy:
    """Test-only boundary seam: canary check, not Bedrock Guardrails or injection detection."""

    def check(self, boundary: str, text: str) -> bool:
        return re.search(r"DEMO_CANARY_[A-Za-z0-9_-]+", text) is None


class OfflineProvider:
    """Scripted choices exercise graphs. This is explicitly not an LLM or quality judge."""

    def respond(self, request: ModelRequest, *, timeout_seconds: float) -> str:
        by_kind = {e.payload.kind: e for e in request.evidence}
        if request.phase == "decide":
            health = by_kind.get("health")
            if not health or health.payload.dependency_state == "healthy":
                for kind, name in (
                    ("health", "get_service_health"),
                    ("changes", "get_recent_changes"),
                    ("logs", "get_recent_logs"),
                    ("runbook", "retrieve_runbook"),
                ):
                    if kind not in by_kind:
                        return ChooseTool(
                            kind="tool",
                            call=tool_call(name),
                            purpose=f"Collect missing {kind} evidence",
                        ).model_dump_json()
        if request.phase == "seed":
            return SearchReply(
                kind="search",
                candidates=(
                    Candidate(candidate_id="deployment", cause="Deployment regression"),
                    Candidate(candidate_id="dependency", cause="Dependency outage"),
                ),
                next_check=tool_call("get_recent_logs"),
                check_purpose="Use release-attributed errors to distinguish candidate causes",
            ).model_dump_json()
        if request.phase == "update":
            health, logs = by_kind.get("health"), by_kind.get("logs")
            healthy = health and health.payload.dependency_state == "healthy"
            candidates = []
            for branch in request.branches:
                if branch.status == "pruned":
                    candidates.append(branch.candidate)
                    continue
                support, oppose = (), ()
                if branch.candidate.candidate_id == "deployment":
                    support = (
                        (logs.evidence_id,)
                        if logs and logs.complete and logs.payload.entries
                        else ()
                    )
                    oppose = (health.evidence_id,) if health and not healthy else ()
                else:
                    support = (health.evidence_id,) if health and not healthy else ()
                    oppose = (health.evidence_id,) if healthy else ()
                candidates.append(
                    Candidate(
                        candidate_id=branch.candidate.candidate_id,
                        cause=branch.candidate.cause,
                        supporting_evidence=support,
                        contradicting_evidence=oppose,
                    )
                )
            return SearchReply(
                kind="search",
                candidates=tuple(candidates),
                next_check=tool_call("retrieve_runbook") if request.round < 2 else None,
                check_purpose="Check current policy applicability before selecting a proposal",
            ).model_dump_json()
        result = investigate(request.run_id, request.evidence, (), request.incident.submitted_at)
        survivors = [b for b in request.branches if b.status == "supported"]
        selected = survivors[0].candidate.candidate_id if len(survivors) == 1 else None
        return Finish(
            kind="finish", investigation=result, selected_candidate_id=selected
        ).model_dump_json()
