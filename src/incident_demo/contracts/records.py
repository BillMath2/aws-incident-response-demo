"""Version-one persisted records. Validation is not authentication or authorization."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from incident_demo.contracts.base import (
    Contract,
    Digest,
    Identifier,
    Release,
    ServiceId,
    Text,
    Timestamp,
    canonical_json,
    content_hash,
)
from incident_demo.contracts.tools import Payload


class Request(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Identifier
    principal_id: Identifier
    service_id: ServiceId
    idempotency_key: Identifier
    submitted_at: Timestamp
    summary: Text


class Versions(Contract):
    model: Identifier
    prompt: Identifier
    tools: Identifier
    fixtures: Identifier


class Usage(Contract):
    model_calls: Annotated[int, Field(ge=0)] = 0
    tool_calls: Annotated[int, Field(ge=0)] = 0
    input_tokens: Annotated[int, Field(ge=0)] = 0
    output_tokens: Annotated[int, Field(ge=0)] = 0


class Run(Contract):
    run_id: Identifier
    request_id: Identifier
    mode: Literal["local_stub", "aws_live"]
    state: Literal[
        "pending",
        "investigating",
        "incomplete",
        "awaiting_approval",
        "rejected",
        "expired",
        "executing",
        "verifying",
        "resolved",
        "unresolved",
        "failed",
        "escalated",
    ]
    versions: Versions
    started_at: Timestamp
    finished_at: Timestamp | None = None
    active_latency_ms: Annotated[int, Field(ge=0)] = 0
    usage: Usage = Usage()
    trace_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finish must not precede start")
        return self


class Evidence(Contract):
    evidence_id: Identifier
    source: Literal[
        "get_service_health", "get_recent_changes", "get_recent_logs", "retrieve_runbook"
    ]
    collected_at: Timestamp
    source_version: Identifier
    content_hash: Digest
    complete: bool
    sanitized: Literal[True]
    payload: Payload

    @model_validator(mode="after")
    def check_integrity(self) -> Self:
        kinds = {
            "get_service_health": "health",
            "get_recent_changes": "changes",
            "get_recent_logs": "logs",
            "retrieve_runbook": "runbook",
        }
        if kinds[self.source] != self.payload.kind:
            raise ValueError("source does not match payload kind")
        if content_hash(self.payload) != self.content_hash:
            raise ValueError("evidence content hash mismatch")
        if len(canonical_json(self).encode("utf-8")) > 32768:
            raise ValueError("evidence exceeds 32 KiB")
        if self.payload.kind == "logs" and self.payload.truncated and self.complete:
            raise ValueError("truncated logs cannot be complete")
        return self


class Finding(Contract):
    statement: Text
    evidence_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=16)]


class Hypothesis(Contract):
    cause: Text
    supporting_evidence: tuple[Identifier, ...] = ()
    contradicting_evidence: tuple[Identifier, ...] = ()
    status: Literal["candidate", "supported", "pruned"]


class Investigation(Contract):
    run_id: Identifier
    outcome: Literal["propose_rollback", "escalate", "incomplete"]
    facts: Annotated[tuple[Finding, ...], Field(max_length=20)]
    hypotheses: Annotated[tuple[Hypothesis, ...], Field(max_length=2)]
    missing_information: tuple[Text, ...]
    next_check: Text | None
    justification: Text


class RollbackArguments(Contract):
    service_id: ServiceId
    target_release: Literal["release-41"]


class ProposalBody(Contract):
    proposal_id: Identifier
    run_id: Identifier
    action: Literal["rollback_demo_release"]
    arguments: RollbackArguments
    expected_current_release: Literal["release-42"]
    evidence_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=16)]
    created_at: Timestamp
    expires_at: Timestamp

    @model_validator(mode="after")
    def valid_expiry(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("proposal expiry must follow creation")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate proposal evidence IDs")
        return self


class Proposal(ProposalBody):
    proposal_hash: Digest

    @model_validator(mode="after")
    def check_hash(self) -> Self:
        if self.proposal_hash != content_hash(
            self.model_dump(mode="json", exclude={"proposal_hash"})
        ):
            raise ValueError("proposal hash mismatch")
        return self

    @classmethod
    def create(cls, **fields) -> Self:
        """Validate server-owned fields before binding every one into the stored hash."""
        body = ProposalBody(**fields)
        return cls(**body.model_dump(), proposal_hash=content_hash(body))


class Approval(Contract):
    approval_id: Identifier
    proposal_id: Identifier
    proposal_hash: Digest
    approver_id: Identifier
    authorized_service: ServiceId
    decision: Literal["approved", "rejected"]
    reason: Text
    decided_at: Timestamp
    expires_at: Timestamp

    @model_validator(mode="after")
    def valid_expiry(self) -> Self:
        if self.decided_at >= self.expires_at:
            raise ValueError("approval decision is already expired")
        return self


class ExecuteRollback(Contract):
    """Executor-only input; arguments are resolved from the persisted proposal."""

    proposal_id: Identifier
    approval_id: Identifier
    idempotency_key: Identifier


class ServiceState(Contract):
    service_id: ServiceId
    release: Release
    revision: Annotated[int, Field(ge=0)]


class ActionReceipt(Contract):
    receipt_id: Identifier
    idempotency_key: Identifier
    proposal_id: Identifier
    proposal_hash: Digest
    before: ServiceState
    after: ServiceState
    status: Literal["applied", "not_applied"]
    audited_at: Timestamp

    @model_validator(mode="after")
    def check_transition(self) -> Self:
        if self.status == "applied":
            if (self.before.release, self.after.release) != ("release-42", "release-41"):
                raise ValueError("only release-42 to release-41 rollback is allowed")
            if self.after.revision != self.before.revision + 1:
                raise ValueError("applied action must increment revision once")
        elif self.before != self.after:
            raise ValueError("not_applied receipt cannot describe a mutation")
        return self


class Evaluation(Contract):
    evaluation_id: Identifier
    case_id: Identifier
    split: Literal["development", "held_out"]
    variant: Literal["V0", "V1", "V2"]
    model: Identifier
    repetition: Annotated[int, Field(ge=1)]
    run_id: Identifier
    expected_outcomes: tuple[Literal["propose_rollback", "escalate", "incomplete"], ...]
    actual_outcome: Literal["propose_rollback", "escalate", "incomplete", "failed", "blocked"]
    usage: Usage
    active_latency_ms: Annotated[int, Field(ge=0)]
    human_verdict: Literal["pending", "pass", "fail"]


def validate_citations(
    investigation: Investigation, evidence: tuple[Evidence, ...], proposal: Proposal | None = None
) -> None:
    """Existence only: semantic support still requires independent review."""
    known = {item.evidence_id for item in evidence}
    if len(known) != len(evidence):
        raise ValueError("duplicate evidence IDs")
    for item in evidence:
        if item.payload.kind == "runbook":
            known.add(item.payload.passage_id)
    cited = {ref for fact in investigation.facts for ref in fact.evidence_ids}
    for hypothesis in investigation.hypotheses:
        cited.update(hypothesis.supporting_evidence)
        cited.update(hypothesis.contradicting_evidence)
    if proposal is not None:
        if proposal.run_id != investigation.run_id:
            raise ValueError("proposal belongs to a different run")
        cited.update(proposal.evidence_ids)
    if cited - known:
        raise ValueError(f"unknown evidence IDs: {sorted(cited - known)}")
