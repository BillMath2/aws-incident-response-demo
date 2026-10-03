"""Local investigation, explicit decision, isolated execution and separate verification."""

from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from incident_demo.contracts.base import content_hash, utc
from incident_demo.contracts.local import AuditEvent, LocalRunRecord
from incident_demo.contracts.records import (
    ActionReceipt,
    Approval,
    Evidence,
    ExecuteRollback,
    Proposal,
    Request,
    RollbackArguments,
    Run,
    ServiceState,
    Usage,
    Versions,
    validate_citations,
)
from incident_demo.corpus import Fixture, KnowledgeCatalog
from incident_demo.investigator.stub import investigate
from incident_demo.local_tools import gather, sanitize, sanitized_evidence
from incident_demo.storage.memory import MemoryStore

# Identities are trusted local demo configuration, not supplied role/privilege fields.
# The CLI may simulate these people. None of this authenticates a real human.
LOCAL_ROLES = {
    "local-analyst": frozenset({"intake"}),
    "local-approver": frozenset({"approve:checkout-api"}),
    "local-executor": frozenset({"execute:checkout-api"}),
    "local-investigator": frozenset(),
}


class WorkflowError(ValueError):
    """Expected control rejection; the run's audit records the reason."""


def evolve(record, **changes):
    """Revalidate changed records rather than using unvalidated model_copy updates."""
    return type(record).model_validate(record.model_dump() | changes)


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


class LocalWorkflow:
    def __init__(self, store: MemoryStore | None = None):
        self.store = store if store is not None else MemoryStore()

    def snapshot(self, run_id: str) -> LocalRunRecord:
        with self.store.lock:
            return self.store.runs[run_id]

    def _event(self, record, now, actor, event, detail, **changes):
        updated = evolve(
            record,
            audit=record.audit
            + (
                AuditEvent(
                    at=now,
                    actor=actor,
                    event=event,
                    detail=sanitize(detail),
                ),
            ),
            **changes,
        )
        self.store.runs[record.run.run_id] = updated
        return updated

    def _deny(self, record, now, actor, message, terminal=None):
        changes = {"service": self.store.service}
        if terminal:
            changes["run"] = evolve(record.run, state=terminal, finished_at=now)
        self._event(record, now, actor, "control_rejected", message, **changes)
        raise WorkflowError(message)

    def start(
        self,
        fixture: Fixture,
        catalog: KnowledgeCatalog,
        *,
        idempotency_key: str,
        now: datetime,
        actor: str = "local-analyst",
    ) -> LocalRunRecord:
        now = utc(now)
        if "intake" not in LOCAL_ROLES.get(actor, ()):
            raise WorkflowError("Actor cannot submit local incidents")
        started = perf_counter()
        fixture_hash, knowledge_hash = content_hash(fixture), content_hash(catalog)
        payload_hash = content_hash({"fixture": fixture_hash, "knowledge": knowledge_hash})
        with self.store.lock:
            previous = self.store.intake.get((actor, idempotency_key))
            if previous:
                if previous[0] != payload_hash:
                    raise WorkflowError("Intake idempotency key reused with different input")
                return self.store.runs[previous[1]]
            request = Request(
                request_id=identifier("request"),
                principal_id=actor,
                service_id=fixture.incident.service_id,
                idempotency_key=idempotency_key,
                submitted_at=now,
                summary=sanitize(fixture.incident.summary),
            )
            run_id = identifier("run")
            evidence, attempts, missing = gather(fixture, catalog, now)
            investigation = investigate(run_id, evidence, missing, now)
            proposal = None
            if investigation.outcome == "propose_rollback":
                proposal = Proposal.create(
                    proposal_id=identifier("proposal"),
                    run_id=run_id,
                    action="rollback_demo_release",
                    arguments=RollbackArguments(
                        service_id="checkout-api", target_release="release-41"
                    ),
                    expected_current_release="release-42",
                    evidence_ids=tuple(e.evidence_id for e in evidence),
                    created_at=now,
                    expires_at=now + timedelta(minutes=15),
                )
            validate_citations(investigation, evidence, proposal)
            state = (
                "awaiting_approval"
                if proposal
                else ("incomplete" if investigation.outcome == "incomplete" else "escalated")
            )
            run = Run(
                run_id=run_id,
                request_id=request.request_id,
                mode="local_stub",
                state=state,
                versions=Versions(
                    model="none-local-stub",
                    prompt="stub-serializer-1.0.0",
                    tools="local-fixtures-1.0.0",
                    fixtures=fixture.fixture_version,
                ),
                started_at=now,
                finished_at=None if proposal else now,
                active_latency_ms=int((perf_counter() - started) * 1000),
                usage=Usage(tool_calls=len(attempts)),
            )
            record = LocalRunRecord(
                fixture_hash=fixture_hash,
                knowledge_hash=knowledge_hash,
                request=request,
                run=run,
                investigation=investigation,
                evidence=evidence,
                tool_attempts=attempts,
                proposal=proposal,
                service=self.store.service,
                audit=(
                    AuditEvent(
                        at=now,
                        actor=actor,
                        event="intake_accepted",
                        detail="Synthetic local intake",
                    ),
                    AuditEvent(
                        at=now,
                        actor="local-investigator",
                        event="investigation_finished",
                        detail=f"Labeled stub returned {investigation.outcome}; zero model calls",
                    ),
                ),
            )
            self.store.runs[run_id] = record
            self.store.intake[(actor, idempotency_key)] = (payload_hash, run_id)
            return record

    def decide(
        self,
        run_id: str,
        *,
        actor: str,
        proposal_hash: str,
        decision: str,
        reason: str,
        now: datetime,
    ) -> LocalRunRecord:
        now = utc(now)
        with self.store.lock:
            record = self.snapshot(run_id)
            if "approve:checkout-api" not in LOCAL_ROLES.get(actor, ()):
                self._deny(record, now, actor, "Actor is not an authorized local approver")
            proposal = record.proposal
            if proposal is None or proposal_hash != proposal.proposal_hash:
                self._deny(record, now, actor, "Decision does not match the stored proposal hash")
            if record.approval:
                previous = record.approval
                if (
                    previous.approver_id,
                    previous.proposal_hash,
                    previous.decision,
                    previous.reason,
                ) == (actor, proposal_hash, decision, sanitize(reason)):
                    return record
                self._deny(record, now, actor, "Conflicting duplicate decision")
            if record.run.state != "awaiting_approval":
                self._deny(record, now, actor, "Run is not awaiting approval")
            if now >= proposal.expires_at:
                self._deny(record, now, actor, "Proposal expired", terminal="expired")
            if now < proposal.created_at:
                self._deny(record, now, actor, "Decision time precedes the proposal")
            approval = Approval(
                approval_id=identifier("approval"),
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal_hash,
                approver_id=actor,
                authorized_service="checkout-api",
                decision=decision,
                reason=sanitize(reason),
                decided_at=now,
                expires_at=proposal.expires_at,
            )
            state = "executing" if decision == "approved" else "rejected"
            return self._event(
                record,
                now,
                actor,
                "decision_recorded",
                decision,
                approval=approval,
                approval_wait_ms=int((now - proposal.created_at).total_seconds() * 1000),
                run=evolve(
                    record.run, state=state, finished_at=None if decision == "approved" else now
                ),
            )

    def execute(
        self, run_id: str, command: ExecuteRollback, *, actor: str, now: datetime
    ) -> ActionReceipt:
        now = utc(now)
        started = perf_counter()
        with self.store.lock:
            record = self.snapshot(run_id)
            if "execute:checkout-api" not in LOCAL_ROLES.get(actor, ()):
                self._deny(record, now, actor, "Actor cannot execute sandbox actions")
            if not record.proposal or command.proposal_id != record.proposal.proposal_id:
                self._deny(record, now, actor, "Executor proposal reference mismatch")
            previous = self.store.actions.get(command.idempotency_key)
            if previous:
                if previous[0] != command:
                    self._deny(
                        record, now, actor, "Action idempotency key reused with different input"
                    )
                return previous[1]
            proposal, approval = record.proposal, record.approval
            if (
                record.run.state != "executing"
                or not approval
                or approval.decision != "approved"
                or record.approval_consumed
                or command.approval_id != approval.approval_id
            ):
                self._deny(record, now, actor, "An unconsumed matching approval is required")
            if (
                approval.proposal_id != proposal.proposal_id
                or approval.proposal_hash != proposal.proposal_hash
                or approval.authorized_service != proposal.arguments.service_id
                or "approve:checkout-api" not in LOCAL_ROLES.get(approval.approver_id, ())
            ):
                self._deny(record, now, actor, "Approval is not bound to this proposal and scope")
            if now >= min(proposal.expires_at, approval.expires_at):
                self._deny(
                    record, now, actor, "Approval expired before execution", terminal="expired"
                )
            if now < approval.decided_at:
                self._deny(record, now, actor, "Execution time precedes approval")
            before = self.store.service
            if before.release != proposal.expected_current_release:
                self._deny(
                    record,
                    now,
                    actor,
                    "Current sandbox release no longer matches proposal",
                    terminal="failed",
                )
            after = ServiceState(
                service_id=before.service_id,
                release=proposal.arguments.target_release,
                revision=before.revision + 1,
            )
            receipt = ActionReceipt(
                receipt_id=identifier("receipt"),
                idempotency_key=command.idempotency_key,
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal.proposal_hash,
                before=before,
                after=after,
                status="applied",
                audited_at=now,
            )
            # Validate the new snapshot before committing all in-memory effects under one lock.
            self._event(
                record,
                now,
                actor,
                "sandbox_action_applied",
                "Synthetic state transition only",
                receipt=receipt,
                approval_consumed=True,
                service=after,
                run=evolve(
                    record.run,
                    state="verifying",
                    active_latency_ms=(
                        record.run.active_latency_ms + int((perf_counter() - started) * 1000)
                    ),
                ),
            )
            self.store.service = after
            self.store.actions[command.idempotency_key] = (command, receipt)
            return receipt

    def verify(self, run_id: str, observation: Evidence | None, *, now: datetime) -> LocalRunRecord:
        now = utc(now)
        started = perf_counter()
        with self.store.lock:
            record = self.snapshot(run_id)
            if record.run.state != "verifying" or record.receipt is None:
                self._deny(record, now, "local-observer", "Run is not awaiting verification")
            evidence = record.evidence
            recovered = False
            detail = "Independent synthetic health observation is missing"
            evidence_id = None
            if observation:
                observation = sanitized_evidence(observation)
                if observation.evidence_id in {e.evidence_id for e in evidence}:
                    self._deny(
                        record,
                        now,
                        "local-observer",
                        "Verification cannot overwrite prior evidence",
                    )
                evidence += (observation,)
                evidence_id = observation.evidence_id
                health = observation.payload
                if health.kind == "health":
                    recovered = (
                        observation.complete
                        and health.service_id == record.service.service_id
                        and record.receipt.audited_at
                        < health.observed_at
                        <= observation.collected_at
                        <= now
                        and now - health.observed_at <= timedelta(minutes=5)
                        and health.release == record.service.release == "release-41"
                        and health.error_rate <= 0.01
                        and health.latency_p95_ms <= 500
                        and health.dependency_state == "healthy"
                    )
                detail = (
                    "Independent synthetic health observation meets recovery criteria"
                    if recovered
                    else "Independent observation failed recovery or freshness criteria"
                )
            return self._event(
                record,
                now,
                "local-observer",
                "verification_finished",
                detail,
                evidence=evidence,
                verification_evidence_id=evidence_id,
                run=evolve(
                    record.run,
                    state="resolved" if recovered else "unresolved",
                    finished_at=now,
                    active_latency_ms=record.run.active_latency_ms
                    + int((perf_counter() - started) * 1000),
                ),
            )

    def export(self, run_id: str, path: Path) -> None:
        """Create a review artifact, never load it as approval authority or resumable state."""
        record = self.snapshot(run_id)
        validate_citations(record.investigation, record.evidence, record.proposal)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(record.model_dump_json(indent=2) + "\n")
