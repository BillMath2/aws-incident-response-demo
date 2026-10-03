"""Export contracts for the explicitly synthetic, single-process local walkthrough."""

from typing import Annotated, Literal

from pydantic import Field

from incident_demo.contracts.base import Contract, Digest, Identifier, Text, Timestamp
from incident_demo.contracts.records import (
    ActionReceipt,
    Approval,
    Evidence,
    Investigation,
    Proposal,
    Request,
    Run,
    ServiceState,
)


class ToolAttempt(Contract):
    name: Literal["get_service_health", "get_recent_changes", "get_recent_logs", "retrieve_runbook"]
    attempt: Annotated[int, Field(ge=1, le=2)]
    status: Literal["ok", "error"]
    error_code: Identifier | None = None
    evidence_ids: tuple[Identifier, ...] = ()


class AuditEvent(Contract):
    at: Timestamp
    actor: Identifier
    event: Identifier
    detail: Text


class LocalRunRecord(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    label: Literal[
        "LOCAL STUB: synthetic telemetry, identities and effects; no AWS or model calls"
    ] = "LOCAL STUB: synthetic telemetry, identities and effects; no AWS or model calls"
    fixture_hash: Digest
    knowledge_hash: Digest
    request: Request
    run: Run
    investigation: Investigation
    evidence: tuple[Evidence, ...]
    tool_attempts: tuple[ToolAttempt, ...]
    proposal: Proposal | None
    approval: Approval | None = None
    approval_consumed: bool = False
    approval_wait_ms: Annotated[int, Field(ge=0)] = 0
    receipt: ActionReceipt | None = None
    verification_evidence_id: Identifier | None = None
    service: ServiceState
    audit: tuple[AuditEvent, ...]
