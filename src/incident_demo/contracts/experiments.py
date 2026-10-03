"""Versioned experiments; offline control-flow evidence cannot satisfy a live gate."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from incident_demo.contracts.base import Contract, Digest, Identifier, Text, Timestamp
from incident_demo.contracts.records import Evidence, Investigation, Usage
from incident_demo.contracts.tools import InvestigatorCall

Variant = Literal["V0", "V1", "V2"]


class Limits(Contract):
    model_calls: Annotated[int, Field(ge=1, le=6)] = 6
    tool_calls: Annotated[int, Field(ge=1, le=8)] = 8
    retries: Annotated[int, Field(ge=0, le=1)] = 1
    deadline_seconds: Annotated[float, Field(gt=0, le=120)] = 120.0
    candidates: Literal[2] = 2
    expansion_rounds: Literal[2] = 2


class Settings(Contract):
    mode: Literal["offline_scripted"] = "offline_scripted"
    model: Literal["offline-scripted-v1"] = "offline-scripted-v1"
    temperature: Literal[0.0] = 0.0
    max_output_tokens: Annotated[int, Field(ge=1, le=4096)] = 2048
    retrieval_limit: Literal[5] = 5
    cache: Literal["disabled"] = "disabled"
    guardrail_policy: Literal["offline-boundary-check-v1"] = "offline-boundary-check-v1"
    limits: Limits = Limits()


class ChooseTool(Contract):
    kind: Literal["tool"]
    call: InvestigatorCall
    purpose: Annotated[str, Field(min_length=1, max_length=600)]


class Finish(Contract):
    kind: Literal["finish"]
    investigation: Investigation
    selected_candidate_id: Identifier | None = None


class Candidate(Contract):
    candidate_id: Identifier
    cause: Annotated[str, Field(min_length=1, max_length=500)]
    supporting_evidence: Annotated[tuple[Identifier, ...], Field(max_length=16)] = ()
    contradicting_evidence: Annotated[tuple[Identifier, ...], Field(max_length=16)] = ()

    @model_validator(mode="after")
    def disjoint_references(self):
        support, oppose = self.supporting_evidence, self.contradicting_evidence
        if (
            len(set(support)) != len(support)
            or len(set(oppose)) != len(oppose)
            or set(support) & set(oppose)
        ):
            raise ValueError("candidate evidence must be unique and disjoint")
        return self


class SearchReply(Contract):
    kind: Literal["search"]
    candidates: Annotated[tuple[Candidate, ...], Field(min_length=1, max_length=2)]
    next_check: InvestigatorCall | None
    check_purpose: Annotated[str, Field(min_length=1, max_length=600)]


Decision = Annotated[ChooseTool | Finish | SearchReply, Field(discriminator="kind")]
DECISION_ADAPTER = TypeAdapter(Decision)


class Branch(Contract):
    candidate: Candidate
    status: Literal["candidate", "supported", "pruned"]
    score: int


class TraceEvent(Contract):
    event: Identifier
    phase: Identifier
    round: Annotated[int, Field(ge=0, le=2)] = 0
    call: InvestigatorCall | None = None
    detail: Annotated[str, Field(min_length=1, max_length=1000)]
    branches: Annotated[tuple[Branch, ...], Field(max_length=2)] = ()


class ExperimentResult(Contract):
    run_id: Identifier
    variant: Variant
    mode: Literal["offline_scripted"] = "offline_scripted"
    status: Literal["complete", "incomplete", "failed", "blocked"]
    stop_reason: Identifier
    investigation: Investigation
    evidence: tuple[Evidence, ...]
    trace: tuple[TraceEvent, ...]
    provider_calls: Annotated[int, Field(ge=0)]
    usage: Usage
    active_latency_ms: Annotated[int, Field(ge=0)]


class Trial(Contract):
    trial_id: Identifier
    case_id: Annotated[str, Field(pattern=r"^case-[0-9]{3}$")]
    variant: Variant
    repetition: Annotated[int, Field(ge=1, le=3)]


class TrialManifest(Contract):
    version: Literal["1.0.0"] = "1.0.0"
    split: Literal["development"] = "development"
    created_at: Timestamp
    settings: Settings
    corpus_sha256: Digest
    prompts_sha256: Digest
    rubric_sha256: Digest
    source_sha256: Digest
    lock_sha256: Digest
    trials: Annotated[tuple[Trial, ...], Field(min_length=24, max_length=72)]

    @model_validator(mode="after")
    def unique_trials(self):
        keys = {(t.case_id, t.variant, t.repetition) for t in self.trials}
        if len(keys) != len(self.trials) or len({t.trial_id for t in self.trials}) != len(
            self.trials
        ):
            raise ValueError("duplicate trials")
        return self


class HumanReview(Contract):
    trial_id: Identifier
    reviewer_id: Identifier
    reviewed_at: Timestamp
    facts_correct: bool
    citations_support_claims: bool
    action_appropriate: bool
    safe_output: bool
    unnecessary_tool_calls: Annotated[int, Field(ge=0)]
    notes: Text


class Score(Contract):
    trial_id: Identifier
    case_id: Identifier
    variant: Variant
    outcome_match: bool
    citations_exist: bool
    required_evidence_present: bool
    human_verdict: Literal["pending", "pass", "fail"]
    case_success: bool | None
