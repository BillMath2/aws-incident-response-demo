import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.local import LocalRunRecord
from incident_demo.contracts.records import ExecuteRollback, Proposal, ServiceState
from incident_demo.corpus import Fixture, load_fixture, load_knowledge
from incident_demo.local_tools import observe_health
from incident_demo.workflow.local import LocalWorkflow, WorkflowError, evolve

NOW = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)


def start(root, case=1, workflow=None, fixture=None, key="intake-1"):
    workflow = workflow or LocalWorkflow()
    record = workflow.start(
        fixture or load_fixture(root / f"fixtures/cases/case-{case:03}.json"),
        load_knowledge(root),
        idempotency_key=key,
        now=NOW,
    )
    return workflow, record


def approve(workflow, record, now=NOW + timedelta(seconds=1)):
    return workflow.decide(
        record.run.run_id,
        actor="local-approver",
        proposal_hash=record.proposal.proposal_hash,
        decision="approved",
        reason="Reviewed synthetic evidence",
        now=now,
    )


def command(record, key="action-1"):
    return ExecuteRollback(
        proposal_id=record.proposal.proposal_id,
        approval_id=record.approval.approval_id,
        idempotency_key=key,
    )


def execute(workflow, record, now=NOW + timedelta(seconds=2)):
    return workflow.execute(record.run.run_id, command(record), actor="local-executor", now=now)


@pytest.mark.parametrize(
    "case,state",
    [
        (1, "awaiting_approval"),
        (2, "escalated"),
        (3, "incomplete"),
        (4, "escalated"),
        (5, "awaiting_approval"),
        (6, "escalated"),
        (7, "escalated"),
        (8, "awaiting_approval"),
    ],
)
def test_development_stories(root, case, state):
    workflow, record = start(root, case)
    assert record.run.state == state
    assert record.run.mode == "local_stub"
    assert record.run.usage.model_calls == 0
    assert record.run.usage.tool_calls <= 8
    assert workflow.store.service.revision == 0
    if state != "awaiting_approval":
        assert record.proposal is None


def test_end_to_end_preserves_evidence_and_exports(root, tmp_path):
    workflow, original = start(root)
    approved = approve(workflow, original)
    receipt = execute(workflow, approved)
    pending = workflow.snapshot(original.run.run_id)
    assert pending.run.state == "verifying"
    assert pending.approval_consumed
    assert receipt.before.release == "release-42"
    assert receipt.after.release == "release-41"
    now = NOW + timedelta(seconds=3)
    observation = observe_health(root, "recovered", now, "verification-1")
    record = workflow.verify(original.run.run_id, observation, now=now)
    assert record.run.state == "resolved"
    assert record.approval_wait_ms == 1000
    assert record.evidence[:-1] == original.evidence
    assert record.evidence[-1].payload.observed_at > receipt.audited_at
    output = tmp_path / "record.json"
    workflow.export(record.run.run_id, output)
    assert LocalRunRecord.model_validate_json(output.read_bytes()) == record
    with pytest.raises(FileExistsError):
        workflow.export(record.run.run_id, output)


@pytest.mark.parametrize("profile", ["unhealthy", "missing"])
def test_failed_verification_is_unresolved(root, profile):
    workflow, record = start(root)
    record = approve(workflow, record)
    execute(workflow, record)
    now = NOW + timedelta(seconds=3)
    observation = observe_health(root, profile, now, "verification-1")
    final = workflow.verify(record.run.run_id, observation, now=now)
    assert final.run.state == "unresolved"
    assert final.receipt.status == "applied"
    assert final.service.revision == 1
    # A later callback cannot rewrite this terminal result into success.
    with pytest.raises(WorkflowError, match="not awaiting verification"):
        workflow.verify(
            record.run.run_id, observe_health(root, "recovered", now, "verification-2"), now=now
        )
    assert workflow.snapshot(record.run.run_id).run.state == "unresolved"


@pytest.mark.parametrize("observed_offset,verified_offset", [(2, 3), (1, 3), (4, 3), (3, 400)])
def test_verification_requires_a_fresh_observation_after_action(
    root, observed_offset, verified_offset
):
    workflow, record = start(root)
    record = approve(workflow, record)
    execute(workflow, record)
    observation = observe_health(
        root, "recovered", NOW + timedelta(seconds=observed_offset), "verification-1"
    )
    final = workflow.verify(
        record.run.run_id, observation, now=NOW + timedelta(seconds=verified_offset)
    )
    assert final.run.state == "unresolved"


def test_verification_cannot_overwrite_prior_evidence(root):
    workflow, record = start(root)
    record = approve(workflow, record)
    execute(workflow, record)
    now = NOW + timedelta(seconds=3)
    observation = observe_health(root, "recovered", now, record.evidence[0].evidence_id)
    with pytest.raises(WorkflowError, match="overwrite"):
        workflow.verify(record.run.run_id, observation, now=now)
    assert workflow.snapshot(record.run.run_id).evidence == record.evidence


@pytest.mark.parametrize(
    "actor", ["local-analyst", "local-investigator", "local-executor", "stranger"]
)
def test_wrong_approver_cannot_mutate(root, actor):
    workflow, record = start(root)
    with pytest.raises(WorkflowError, match="authorized local approver"):
        workflow.decide(
            record.run.run_id,
            actor=actor,
            proposal_hash=record.proposal.proposal_hash,
            decision="approved",
            reason="Try bypass",
            now=NOW,
        )
    assert workflow.store.service.revision == 0
    assert workflow.snapshot(record.run.run_id).approval is None


@pytest.mark.parametrize("actor", ["local-analyst", "local-investigator", "local-approver"])
def test_wrong_executor_cannot_mutate(root, actor):
    workflow, record = start(root)
    record = approve(workflow, record)
    with pytest.raises(WorkflowError, match="cannot execute"):
        workflow.execute(
            record.run.run_id, command(record), actor=actor, now=NOW + timedelta(seconds=2)
        )
    assert workflow.store.service.revision == 0


def test_execution_without_approval_and_after_rejection(root):
    workflow, record = start(root)
    request = ExecuteRollback(
        proposal_id=record.proposal.proposal_id,
        approval_id="fabricated-approval",
        idempotency_key="action-1",
    )
    with pytest.raises(WorkflowError, match="unconsumed matching approval"):
        workflow.execute(record.run.run_id, request, actor="local-executor", now=NOW)
    rejected = workflow.decide(
        record.run.run_id,
        actor="local-approver",
        proposal_hash=record.proposal.proposal_hash,
        decision="rejected",
        reason="Insufficient confidence",
        now=NOW,
    )
    with pytest.raises(WorkflowError):
        execute(workflow, rejected)
    with pytest.raises(WorkflowError, match="Conflicting duplicate"):
        approve(workflow, record)
    assert workflow.snapshot(record.run.run_id).run.state == "rejected"
    assert workflow.store.service.revision == 0


def test_approval_hash_must_match_and_proposal_cannot_change_after_decision(root):
    workflow, record = start(root)
    with pytest.raises(WorkflowError, match="proposal hash"):
        workflow.decide(
            record.run.run_id,
            actor="local-approver",
            proposal_hash="0" * 64,
            decision="approved",
            reason="Wrong proposal",
            now=NOW,
        )
    approved = approve(workflow, record)
    fields = approved.proposal.model_dump(exclude={"proposal_hash"})
    edited = Proposal.create(**(fields | {"expires_at": NOW + timedelta(minutes=14)}))
    workflow.store.runs[record.run.run_id] = evolve(approved, proposal=edited)
    with pytest.raises(WorkflowError, match="bound"):
        execute(workflow, approved)
    assert workflow.store.service.revision == 0


@pytest.mark.parametrize("decision_first", [False, True])
def test_expiry_blocks_late_decision_or_execution(root, decision_first):
    workflow, record = start(root)
    expiry = record.proposal.expires_at
    with pytest.raises(WorkflowError, match="expired"):
        if decision_first:
            record = approve(workflow, record)
            execute(workflow, record, now=expiry)
        else:
            approve(workflow, record, now=expiry)
    assert workflow.snapshot(record.run.run_id).run.state == "expired"
    assert workflow.store.service.revision == 0
    with pytest.raises(WorkflowError):
        workflow.execute(
            record.run.run_id,
            ExecuteRollback(
                proposal_id=record.proposal.proposal_id,
                approval_id="late",
                idempotency_key="action-late",
            ),
            actor="local-executor",
            now=expiry + timedelta(seconds=1),
        )


def test_stale_service_release_blocks_execution(root):
    workflow, record = start(root)
    record = approve(workflow, record)
    workflow.store.service = ServiceState(
        service_id="checkout-api", release="release-41", revision=7
    )
    with pytest.raises(WorkflowError, match="no longer matches"):
        execute(workflow, record)
    assert workflow.store.service.revision == 7
    assert workflow.snapshot(record.run.run_id).run.state == "failed"
    assert not workflow.snapshot(record.run.run_id).approval_consumed


def test_duplicate_decisions_and_actions_are_idempotent_in_one_process(root):
    workflow, record = start(root)
    approved = approve(workflow, record)
    assert approve(workflow, record) == approved
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: execute(workflow, approved), range(2)))
    assert receipts[0] == receipts[1]
    assert workflow.store.service.revision == 1
    assert execute(workflow, approved, now=NOW + timedelta(hours=1)) == receipts[0]
    with pytest.raises(WorkflowError):
        workflow.execute(
            record.run.run_id,
            command(approved, "another-key"),
            actor="local-executor",
            now=NOW + timedelta(seconds=4),
        )
    assert workflow.store.service.revision == 1


def test_action_key_cannot_be_reused_for_another_run(root):
    workflow, first = start(root)
    _, second = start(root, workflow=workflow, key="intake-2")
    first, second = approve(workflow, first), approve(workflow, second)
    execute(workflow, first)
    with pytest.raises(WorkflowError, match="different input"):
        execute(workflow, second)
    assert workflow.store.service.revision == 1


def test_intake_replay_is_scoped_and_rejects_changed_payload(root):
    workflow, original = start(root)
    _, replay = start(root, workflow=workflow)
    assert replay == original
    with pytest.raises(WorkflowError, match="different input"):
        start(root, case=2, workflow=workflow)


def test_transient_retry_is_bounded_and_persistent_failure_stays_incomplete(root):
    workflow, transient = start(root, case=5)
    logs = [a for a in transient.tool_attempts if a.name == "get_recent_logs"]
    assert [a.status for a in logs] == ["error", "ok"]
    assert transient.run.usage.tool_calls == 5
    raw = load_fixture(root / "fixtures/cases/case-005.json").model_dump(mode="json")
    raw["responses"][-1] = raw["responses"][-2]
    fixture = Fixture.model_validate_json(json.dumps(raw))
    _, failed = start(root, fixture=fixture)
    assert failed.run.state == "incomplete"
    assert len([a for a in failed.tool_attempts if a.name == "get_recent_logs"]) == 2
    assert failed.proposal is None


def test_stub_uses_evidence_not_case_ids_and_redacts_synthetic_canaries(root, tmp_path):
    data = load_fixture(root / "fixtures/cases/case-001.json").model_dump(mode="json")
    data["incident"]["summary"] = "Inspect checkout DEMO_CANARY_FAKE123\u001b[31m"
    for response in data["responses"]:
        response["evidence"]["evidence_id"] += "-renamed"
    log = data["responses"][-1]["evidence"]
    log["payload"]["entries"][0]["message"] += " DEMO_CANARY_FAKE456"
    log["content_hash"] = content_hash(log["payload"])
    workflow, record = start(root, fixture=Fixture.model_validate_json(json.dumps(data)))
    assert record.proposal is not None
    output = tmp_path / "record.json"
    workflow.export(record.run.run_id, output)
    text = output.read_text()
    assert "DEMO_CANARY_FAKE" not in text
    assert "SYNTHETIC_CANARY_REDACTED" in text
    assert "\u001b" not in text
