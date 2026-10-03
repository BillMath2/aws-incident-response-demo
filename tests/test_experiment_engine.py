import json
import socket

import pytest

from incident_demo.contracts.experiments import Limits, Settings
from incident_demo.corpus import load_fixture, load_knowledge
from incident_demo.investigator.engine import Engine
from incident_demo.investigator.providers import (
    FixtureTools,
    OfflineProvider,
    TransientFailure,
)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline experiment attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")


def engine(root, variant="V0", case=1, provider=None, settings=None, policy=None, clock=None):
    fixture = load_fixture(root / f"fixtures/cases/case-{case:03}.json")
    options = {"clock": clock} if clock else {}
    return Engine(
        root,
        variant,
        fixture.incident,
        provider or OfflineProvider(),
        FixtureTools(fixture, load_knowledge(root)),
        settings,
        policy,
        **options,
    )


class TransformProvider:
    def __init__(self, transform):
        self.transform = transform
        self.requests = []

    def respond(self, request, *, timeout_seconds):
        self.requests.append(request)
        assert 0 < timeout_seconds <= 120
        raw = json.loads(OfflineProvider().respond(request, timeout_seconds=timeout_seconds))
        return json.dumps(self.transform(request, raw))


@pytest.mark.parametrize("variant,calls", [("V0", 1), ("V1", 5), ("V2", 4)])
def test_executable_graphs_share_inputs_and_return_structured_results(root, variant, calls):
    provider = TransformProvider(lambda req, raw: raw)
    result = engine(root, variant, provider=provider).run()
    assert result.status == "complete"
    assert result.investigation.outcome == "propose_rollback"
    assert result.provider_calls == calls
    assert result.usage.model_calls == result.usage.input_tokens == result.usage.output_tokens == 0
    assert result.usage.tool_calls == 4
    for request in provider.requests:
        assert (
            not {"case_id", "expected_facts", "acceptable_outcomes", "split", "category"}
            & vars(request).keys()
        )
        assert "private chain-of-thought" in request.system_prompt
        assert request.response_schema and request.tool_schema
    assert [e.phase for e in result.trace if e.event == "provider_attempt"][0] == {
        "V0": "final",
        "V1": "decide",
        "V2": "seed",
    }[variant]


def test_react_observes_then_changes_tool_sequence(root):
    healthy = engine(root, "V1", case=1).run()
    degraded = engine(root, "V1", case=2).run()
    assert healthy.usage.tool_calls == 4
    assert degraded.usage.tool_calls == 1
    assert degraded.investigation.outcome == "escalate"


def test_v2_expands_updates_prunes_and_stops_after_two_rounds(root):
    result = engine(root, "V2").run()
    states = [e for e in result.trace if e.event == "search_state"]
    assert [s.round for s in states] == [0, 1, 2]
    assert all(len(s.branches) == 2 for s in states)
    assert states[0].call.name == "get_recent_logs"
    assert states[1].call.name == "retrieve_runbook"
    assert states[2].call is None
    assert states[0].branches[1].status == "candidate"
    assert states[1].branches[1].status == states[2].branches[1].status == "pruned"
    assert states[2].branches[0].status == "supported"


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("third_candidate", "contract_or_citation_invalid"),
        ("duplicate_candidate", "duplicate_candidates"),
        ("changed_identity", "candidate_identity_changed"),
        ("fabricated_search_citation", "invented_search_citation"),
        ("revive_pruned", "pruned_branch_changed"),
        ("extra_round", "search_round_limit"),
        ("no_check", "search_requires_check"),
        ("wrong_selection", "search_selection_unsupported"),
        ("tie", "search_selection_unsupported"),
    ],
)
def test_v2_rejects_invalid_search_transitions(root, fault, reason):
    def transform(req, raw):
        if req.phase == "seed":
            if fault == "third_candidate":
                raw["candidates"].append(raw["candidates"][0])
            if fault == "duplicate_candidate":
                raw["candidates"][1] = raw["candidates"][0]
            if fault == "no_check":
                raw["next_check"] = None
        if req.phase == "update":
            if fault == "changed_identity":
                raw["candidates"][0]["candidate_id"] = "replaced"
            if fault == "fabricated_search_citation":
                raw["candidates"][0]["supporting_evidence"] = ["invented"]
            if fault == "tie":
                for candidate in raw["candidates"]:
                    candidate["supporting_evidence"] = ["obs-001-logs"]
                    candidate["contradicting_evidence"] = []
            if req.round == 2:
                if fault == "revive_pruned":
                    raw["candidates"][1]["contradicting_evidence"] = []
                if fault == "extra_round":
                    raw["next_check"] = {
                        "name": "get_service_health",
                        "arguments": {"service_id": "checkout-api"},
                    }
        if req.phase == "final" and fault == "wrong_selection":
            raw["selected_candidate_id"] = "dependency"
        return raw

    result = engine(root, "V2", provider=TransformProvider(transform)).run()
    assert result.status == "failed"
    assert result.stop_reason == reason
    assert result.investigation.outcome == "incomplete"
    assert result.provider_calls <= 6 and result.usage.tool_calls <= 8


def test_all_pruned_escalates_without_generating_finished_drafts(root):
    def transform(req, raw):
        if req.phase == "update":
            for c in raw["candidates"]:
                c["supporting_evidence"] = []
                c["contradicting_evidence"] = ["obs-001-health"]
        return raw

    result = engine(root, "V2", provider=TransformProvider(transform)).run()
    assert result.status == "complete"
    assert result.investigation.outcome == "escalate"
    assert result.provider_calls == 2


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("not json", "contract_or_citation_invalid"),
        ("x" * 32769, "oversized_model_output"),
        (
            '{"kind":"tool","call":{"name":"rollback_demo_release","arguments":{}},"purpose":"execute"}',
            "contract_or_citation_invalid",
        ),
    ],
    ids=["invalid-json", "oversized", "privileged-tool"],
)
def test_malformed_oversized_and_privileged_decisions_fail_closed(root, raw, reason):
    class BadProvider:
        def respond(self, request, **kwargs):
            return raw

    result = engine(root, "V1", provider=BadProvider()).run()
    assert result.status == "failed"
    assert result.stop_reason == reason
    assert result.usage.tool_calls == 0


def test_invented_final_citation_is_rejected(root):
    def transform(req, raw):
        raw["investigation"]["facts"][0]["evidence_ids"] = ["fabricated"]
        return raw

    result = engine(root, provider=TransformProvider(transform)).run()
    assert result.stop_reason == "contract_or_citation_invalid"


@pytest.mark.parametrize("case", [2, 3, 6, 7])
def test_proposal_requires_fresh_complete_evidence_and_current_policy(root, case):
    def transform(req, raw):
        raw["investigation"]["outcome"] = "propose_rollback"
        return raw

    result = engine(root, case=case, provider=TransformProvider(transform)).run()
    assert result.status == "failed"
    assert result.stop_reason in {"proposal_preconditions_failed", "missing_proposal_evidence"}


def test_no_private_reasoning_field_is_accepted(root):
    provider = TransformProvider(lambda req, raw: raw | {"private_reasoning": "hidden transcript"})
    result = engine(root, provider=provider).run()
    assert result.status == "failed"
    assert "hidden transcript" not in result.model_dump_json()


@pytest.mark.parametrize(
    "limit,reason,count",
    [("model", "model_budget_exhausted", 6), ("tool", "tool_budget_exhausted", 2)],
)
def test_repeated_tool_requests_obey_global_budgets(root, limit, reason, count):
    def transform(req, raw):
        return {
            "kind": "tool",
            "call": {"name": "get_service_health", "arguments": {"service_id": "checkout-api"}},
            "purpose": "Repeated probe",
        }

    settings = Settings(limits=Limits(tool_calls=2 if limit == "tool" else 8))
    result = engine(root, "V1", provider=TransformProvider(transform), settings=settings).run()
    assert result.status == "incomplete" and result.stop_reason == reason
    assert (result.provider_calls if limit == "model" else result.usage.tool_calls) == count


@pytest.mark.parametrize("recover", [False, True])
def test_transient_model_retries_count_against_total(root, recover):
    class Flaky(OfflineProvider):
        count = 0

        def respond(self, req, **kwargs):
            self.count += 1
            if self.count == 1 or not recover:
                raise TransientFailure()
            return super().respond(req, **kwargs)

    result = engine(root, provider=Flaky()).run()
    assert result.provider_calls == 2
    assert result.status == ("complete" if recover else "incomplete")
    if not recover:
        assert result.stop_reason == "model_retry_exhausted"


def test_tool_retry_is_counted_and_does_not_reset_budget(root):
    result = engine(root, case=5).run()
    assert result.status == "complete" and result.usage.tool_calls == 5
    result = engine(root, case=5, settings=Settings(limits=Limits(tool_calls=3))).run()
    assert result.usage.tool_calls == 3
    assert result.stop_reason == "tool_budget_exhausted"


def test_deadline_discards_a_late_provider_result(root):
    clock = [0.0]

    class Late(OfflineProvider):
        def respond(self, req, **kwargs):
            result = super().respond(req, **kwargs)
            clock[0] = 121.0
            return result

    result = engine(root, provider=Late(), clock=lambda: clock[0]).run()
    assert result.status == "incomplete" and result.stop_reason == "deadline_exhausted"
    assert result.provider_calls == 1


@pytest.mark.parametrize("boundary", ["input", "source", "output"])
@pytest.mark.parametrize("unavailable", [False, True])
def test_filter_boundaries_fail_closed(root, boundary, unavailable):
    class Policy:
        def check(self, name, text):
            if name == boundary:
                if unavailable:
                    raise RuntimeError("private backend failure details")
                return False
            return True

    result = engine(root, policy=Policy()).run()
    assert result.status == ("failed" if unavailable else "blocked")
    assert result.stop_reason == ("filter_unavailable" if unavailable else "filter_blocked")
    assert "private backend failure" not in result.model_dump_json()


def test_benign_canary_prefix_documentation_does_not_block(root):
    result = engine(root, case=8).run()
    assert result.status == "complete"
    assert result.investigation.outcome == "propose_rollback"


def test_output_canary_is_blocked_without_retaining_value(root):
    def transform(req, raw):
        raw["investigation"]["justification"] = "DEMO_CANARY_SYNTHETIC_TEST_VALUE"
        return raw

    result = engine(root, provider=TransformProvider(transform)).run()
    assert result.status == "blocked"
    assert "DEMO_CANARY_SYNTHETIC_TEST_VALUE" not in result.model_dump_json()


def test_engine_state_is_not_reused_between_cases(root):
    single = engine(root)
    single.run()
    with pytest.raises(ValueError, match="reused"):
        single.run()
