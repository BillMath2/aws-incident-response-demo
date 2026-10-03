import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.records import (
    ActionReceipt,
    Approval,
    Evidence,
    ExecuteRollback,
    Finding,
    Investigation,
    Proposal,
    Request,
    RollbackArguments,
    ServiceState,
    validate_citations,
)
from incident_demo.contracts.tools import CALL_ADAPTER
from incident_demo.corpus import load_fixture, load_knowledge

NOW = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)


def proposal(**overrides) -> Proposal:
    fields = dict(
        proposal_id="proposal-001",
        run_id="run-001",
        action="rollback_demo_release",
        arguments=RollbackArguments(service_id="checkout-api", target_release="release-41"),
        expected_current_release="release-42",
        evidence_ids=("obs-001-health",),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    return Proposal.create(**(fields | overrides))


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_service_health", {"service_id": "checkout-api"}),
        ("get_recent_changes", {"service_id": "checkout-api", "window_minutes": 60}),
        ("get_recent_logs", {"service_id": "checkout-api", "filter": "errors", "limit": 10}),
        ("retrieve_runbook", {"service_id": "checkout-api", "query": "checkout regression"}),
    ],
)
def test_only_read_only_calls_are_valid(name, arguments):
    assert (
        CALL_ADAPTER.validate_json(json.dumps({"name": name, "arguments": arguments})).name == name
    )


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "null",
        json.dumps({"name": "rollback_demo_release", "arguments": {"service_id": "checkout-api"}}),
        json.dumps({"name": "approve", "arguments": {"service_id": "checkout-api"}}),
        json.dumps({"name": "get_service_health", "arguments": {"service_id": "production-api"}}),
        json.dumps(
            {
                "name": "get_service_health",
                "arguments": {"service_id": "checkout-api", "url": "https://example.invalid"},
            }
        ),
        json.dumps(
            {
                "name": "get_recent_logs",
                "arguments": {"service_id": "checkout-api", "filter": "rm -rf /"},
            }
        ),
        json.dumps(
            {"name": "get_recent_logs", "arguments": {"service_id": "checkout-api", "limit": 51}}
        ),
        json.dumps(
            {"name": "get_recent_logs", "arguments": {"service_id": "checkout-api", "limit": "2"}}
        ),
        json.dumps(
            {"name": "get_recent_logs", "arguments": {"service_id": "checkout-api", "limit": True}}
        ),
        json.dumps(
            {
                "name": "get_recent_changes",
                "arguments": {"service_id": "checkout-api", "window_minutes": 121},
            }
        ),
        json.dumps(
            {
                "name": "retrieve_runbook",
                "arguments": {"service_id": "checkout-api", "query": "x" * 501},
            }
        ),
    ],
)
def test_reject_invalid_or_privileged_tool_calls(raw):
    with pytest.raises(ValidationError):
        CALL_ADAPTER.validate_json(raw)


def test_request_rejects_client_privilege_and_naive_time():
    data = dict(
        request_id="req-1",
        principal_id="analyst-1",
        service_id="checkout-api",
        idempotency_key="key-1",
        submitted_at=NOW,
        summary="Errors are rising",
    )
    with pytest.raises(ValidationError):
        Request(**data, role="admin")
    with pytest.raises(ValidationError, match="timezone"):
        Request(**(data | {"submitted_at": NOW.replace(tzinfo=None)}))


def test_evidence_is_deeply_immutable_and_round_trips(root):
    original = load_fixture(root / "fixtures/cases/case-001.json").responses[0].evidence
    assert Evidence.model_validate_json(original.model_dump_json()) == original
    with pytest.raises(ValidationError):
        original.payload.error_rate = 0.0
    with pytest.raises(ValidationError):
        original.complete = False


def test_evidence_rejects_hash_tampering_and_source_mismatch(root):
    original = load_fixture(root / "fixtures/cases/case-001.json").responses[0].evidence
    data = original.model_dump(mode="json")
    data["payload"]["error_rate"] = 0.99
    with pytest.raises(ValidationError, match="hash mismatch"):
        Evidence.model_validate_json(json.dumps(data))
    data = original.model_dump(mode="json") | {"source": "get_recent_logs"}
    with pytest.raises(ValidationError, match="source does not match"):
        Evidence.model_validate_json(json.dumps(data))


def test_evidence_rejects_oversized_and_truncated_complete_results(root):
    original = load_fixture(root / "fixtures/cases/case-001.json").responses[-1].evidence
    data = original.model_dump(mode="json")
    data["payload"]["entries"] = [{"observed_at": NOW.isoformat(), "message": "x" * 2000}] * 20
    # Hash the normalized payload, as producers must.
    payload = original.payload.__class__.model_validate_json(json.dumps(data["payload"]))
    data["content_hash"] = content_hash(payload)
    with pytest.raises(ValidationError, match="32 KiB"):
        Evidence.model_validate_json(json.dumps(data))
    data = original.model_dump(mode="json")
    data["payload"]["truncated"] = True
    data["content_hash"] = content_hash(data["payload"])
    with pytest.raises(ValidationError, match="truncated logs"):
        Evidence.model_validate_json(json.dumps(data))


def test_citations_check_existence_but_do_not_claim_semantic_support(root):
    evidence = tuple(
        r.evidence for r in load_fixture(root / "fixtures/cases/case-001.json").responses
    )
    investigation = Investigation(
        run_id="run-001",
        outcome="escalate",
        facts=(Finding(statement="The moon is cheese", evidence_ids=("obs-001-health",)),),
        hypotheses=(),
        missing_information=(),
        next_check=None,
        justification="Needs human review",
    )
    validate_citations(investigation, evidence)
    data = investigation.model_dump(mode="json")
    data["facts"][0]["evidence_ids"] = ["invented-evidence"]
    bad = Investigation.model_validate_json(json.dumps(data))
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_citations(bad, evidence)
    with pytest.raises(ValueError, match="duplicate evidence"):
        validate_citations(investigation, evidence + evidence)
    with pytest.raises(ValueError, match="different run"):
        validate_citations(investigation, evidence, proposal(run_id="run-other"))


def test_proposal_hash_binds_fields_and_is_canonical():
    first = proposal()
    reversed_fields = dict(reversed(list(first.model_dump(mode="json").items())))
    assert (
        Proposal.model_validate_json(json.dumps(reversed_fields)).proposal_hash
        == first.proposal_hash
    )
    for changes in (
        {"run_id": "run-002"},
        {"expires_at": NOW + timedelta(minutes=14)},
        {"evidence_ids": ("obs-001-logs",)},
    ):
        assert proposal(**changes).proposal_hash != first.proposal_hash
    with pytest.raises(ValidationError):
        proposal(expires_at=NOW)
    with pytest.raises(ValidationError):
        proposal(expected_current_release="release-41")
    with pytest.raises(ValidationError):
        RollbackArguments(service_id="checkout-api", target_release="release-40")


def test_approval_and_executor_contracts_do_not_accept_tokens_or_arguments():
    fields = dict(
        approval_id="approval-1",
        proposal_id="proposal-001",
        proposal_hash=proposal().proposal_hash,
        approver_id="approver-1",
        authorized_service="checkout-api",
        decision="approved",
        reason="Reviewed evidence",
        decided_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    assert Approval(**fields).decision == "approved"
    with pytest.raises(ValidationError):
        Approval(**fields, callback_token="server-only-secret")
    with pytest.raises(ValidationError):
        Approval(**(fields | {"expires_at": NOW}))
    with pytest.raises(ValidationError):
        ExecuteRollback(
            proposal_id="proposal-001",
            approval_id="approval-1",
            idempotency_key="execute-1",
            arguments={"target_release": "release-41"},
        )


def test_stored_proposal_rejects_edits_without_a_new_hash():
    original = proposal()
    assert Proposal.model_validate_json(original.model_dump_json()) == original
    data = original.model_dump(mode="json")
    data["expires_at"] = (NOW + timedelta(hours=1)).isoformat()
    with pytest.raises(ValidationError, match="proposal hash mismatch"):
        Proposal.model_validate_json(json.dumps(data))


def test_runbook_passage_citations_are_supported(root):
    passage = load_knowledge(root).documents[0].passage
    evidence = Evidence(
        evidence_id="retrieval-1",
        source="retrieve_runbook",
        collected_at=NOW,
        source_version=passage.version,
        content_hash=content_hash(passage),
        complete=True,
        sanitized=True,
        payload=passage,
    )
    investigation = Investigation(
        run_id="run-1",
        outcome="escalate",
        facts=(Finding(statement="Approval is required", evidence_ids=(passage.passage_id,)),),
        hypotheses=(),
        missing_information=(),
        next_check=None,
        justification="Read the policy",
    )
    validate_citations(investigation, (evidence,))


def test_receipt_never_claims_recovery_and_rejects_invalid_transitions():
    fields = dict(
        receipt_id="receipt-1",
        idempotency_key="execute-1",
        proposal_id="proposal-001",
        proposal_hash=proposal().proposal_hash,
        before=ServiceState(service_id="checkout-api", release="release-42", revision=0),
        after=ServiceState(service_id="checkout-api", release="release-41", revision=1),
        status="applied",
        audited_at=NOW,
    )
    assert ActionReceipt(**fields).status == "applied"
    with pytest.raises(ValidationError):
        ActionReceipt(**(fields | {"status": "recovered"}))
    with pytest.raises(ValidationError):
        ActionReceipt(**(fields | {"status": "not_applied"}))
    with pytest.raises(ValidationError):
        ActionReceipt(**(fields | {"after": fields["before"]}))
