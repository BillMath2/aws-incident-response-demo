"""Offline P05 checks: enforce limits before billed I/O and stop hung workers."""
# ruff: noqa: E402

import json
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

pytest.importorskip("boto3")

from incident_demo.contracts.experiments import LiveSettings
from incident_demo.investigator.providers import ToolFailure, TransientFailure, tool_call
from incident_demo.live.adapters import (
    CountedClient,
    LambdaTools,
    decode_response,
    inline_schema,
    response_phase,
    response_tools,
)
from incident_demo.live.contracts import DiagnosticRequest, LiveRequest
from incident_demo.live.diagnostics import diagnose
from incident_demo.live.runtime import run_bounded

ROOT = Path(__file__).resolve().parents[1]


def request():
    fixture = json.loads((ROOT / "fixtures/cases/case-001.json").read_text())
    return LiveRequest.model_validate_json(
        json.dumps(
            {
                "run_id": "test-run",
                "batch_id": "test-batch",
                "telemetry_id": "a" * 24,
                "incident": fixture["incident"],
                "settings": {"model": "us.amazon.nova-lite-v1:0"},
            }
        )
    )


def test_native_response_bounds_execution_and_rejects_unknown_or_invalid_calls():
    request = SimpleNamespace(phase="decide", variant="V1", evidence=())
    tools = response_tools(request)
    valid = {"name": "get_service_health", "args": {"service_id": "checkout-api"}}

    def reply(calls, reason="tool_use"):
        return SimpleNamespace(tool_calls=calls, response_metadata={"stopReason": reason})

    assert json.loads(decode_response(reply([valid]), request, tools))["kind"] == "tool"
    assert decode_response(reply([valid, valid]), request, tools) == decode_response(
        reply([valid]), request, tools
    )
    for invalid in (
        reply([valid] * 5),
        reply([valid], "end_turn"),
        reply([{"name": "executor", "args": {}}]),
        reply([{"name": "get_service_health", "args": {"service_id": "other"}}]),
        reply(
            [{"name": "get_service_health", "args": {"service_id": "checkout-api", "extra": True}}]
        ),
    ):
        with pytest.raises(ValueError):
            decode_response(invalid, request, tools)


def test_live_schema_exposes_only_the_current_graph_phase():
    def names_for(phase, variant="V1"):
        return {
            t["function"]["name"]
            for t in response_tools(SimpleNamespace(phase=phase, variant=variant, evidence=()))
        }

    assert names_for("decide") == {
        "get_service_health",
        "get_recent_changes",
        "get_recent_logs",
        "finish_investigation",
    }
    assert names_for("final") == {"finish_investigation"}
    assert names_for("seed", "V2") == {"submit_search"}
    names = ("get_service_health", "get_recent_changes", "get_recent_logs")
    evidence = tuple(SimpleNamespace(source=name) for name in names)
    assert response_phase(SimpleNamespace(phase="decide", evidence=evidence[:2])) == "decide"
    assert response_phase(SimpleNamespace(phase="decide", evidence=evidence)) == "final"
    assert response_phase(SimpleNamespace(phase="update", evidence=evidence)) == "update"


def test_inline_model_schema_preserves_nested_contract_constraints():
    from incident_demo.contracts.records import Investigation

    schema = inline_schema(Investigation.model_json_schema())
    assert "$ref" not in json.dumps(schema) and "$defs" not in json.dumps(schema)
    assert schema["additionalProperties"] is False
    assert "facts" in schema["required"]
    fact = schema["properties"]["facts"]["items"]
    assert fact["properties"]["evidence_ids"]["minItems"] == 1


def test_input_cap_prevents_any_billed_request():
    class Client:
        def count_tokens(self, **kwargs):
            return {"inputTokens": 6001}

        def converse(self, **kwargs):
            pytest.fail("oversized input reached billed operation")

    usage = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
    client = CountedClient(Client(), lambda *args, **kwargs: None, usage)
    with pytest.raises(ValueError, match="input token"):
        client.converse(modelId="allowed", messages=[], inferenceConfig={"maxTokens": 1500})
    assert usage["model_calls"] == 0


def test_nova_counting_fallback_is_explicit_and_narrow():
    class Unsupported(Exception):
        pass

    class Client:
        exceptions = SimpleNamespace(ValidationException=Unsupported)

        def count_tokens(self, **kwargs):
            raise Unsupported("The provided model doesn't support counting tokens.")

        def converse(self, **kwargs):
            return {
                "usage": {"inputTokens": 100, "outputTokens": 20},
                "ResponseMetadata": {"RequestId": "model-request"},
            }

    usage = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
    events = []
    client = CountedClient(Client(), lambda event, **kwargs: events.append(event), usage)
    client.converse(
        modelId="us.amazon.nova-lite-v1:0", messages=[], inferenceConfig={"maxTokens": 1500}
    )
    assert events == ["token_count_unsupported", "model_started", "model_finished"]
    with pytest.raises(Unsupported):
        client.converse(modelId="other-model", messages=[], inferenceConfig={"maxTokens": 1500})
    with pytest.raises(ValueError, match="byte cap"):
        client.converse(
            modelId="us.amazon.nova-lite-v1:0",
            messages=["x" * 32769],
            inferenceConfig={"maxTokens": 1500},
        )
    assert usage["model_calls"] == 1


def test_unknown_billed_call_is_still_counted():
    class Client:
        def count_tokens(self, **kwargs):
            return {"inputTokens": 500}

        def converse(self, **kwargs):
            raise TimeoutError()

    usage = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
    events = []
    client = CountedClient(Client(), lambda event, **kwargs: events.append(event), usage)
    with pytest.raises(TimeoutError):
        client.converse(modelId="allowed", messages=[], inferenceConfig={"maxTokens": 1500})
    assert usage["model_calls"] == 1
    assert events == ["model_started"]


def test_hard_deadline_kills_an_uncooperative_process(tmp_path):
    marker = tmp_path / "late-effect.txt"
    code = "import pathlib,time; time.sleep(2); pathlib.Path(" + repr(str(marker)) + ").touch()"
    before = time.monotonic()
    assert run_bounded([sys.executable, "-c", code], 0.15) == (False, True)
    assert time.monotonic() - before < 2
    assert not marker.exists()


def test_live_contract_rejects_unknown_models_and_widened_limits():
    with pytest.raises(ValidationError):
        LiveSettings(model="unapproved-model")
    with pytest.raises(ValidationError):
        LiveSettings(model="us.amazon.nova-lite-v1:0", max_output_tokens=4096)
    with pytest.raises(ValidationError):
        LiveRequest.model_validate_json(request().model_dump_json().replace('"V1"', '"shell"'))


def test_lambda_handler_enforces_tool_identity_and_transient_sequence():
    fixture = json.loads((ROOT / "fixtures/cases/case-005.json").read_text())
    catalog = {"a" * 24: {"responses": fixture["responses"]}}
    values = {
        "run_id": "run",
        "telemetry_id": "a" * 24,
        "attempt": 1,
        "call": tool_call("get_recent_logs").model_dump(mode="json"),
    }
    call = DiagnosticRequest.model_validate_json(json.dumps(values))
    assert diagnose(call, catalog, "get_recent_logs") == {"status": "error", "retryable": True}
    with pytest.raises(ValueError):
        diagnose(call, catalog, "get_service_health")
    assert (
        diagnose(call.model_copy(update={"attempt": 2}), catalog, "get_recent_logs")["status"]
        == "ok"
    )


@pytest.mark.parametrize(
    "response,error",
    [
        ({"status": "error", "retryable": True}, TransientFailure),
        ({"status": "error", "retryable": False}, ToolFailure),
    ],
)
def test_lambda_error_is_not_fabricated_evidence(response, error):
    class Client:
        exceptions = SimpleNamespace(TooManyRequestsException=ConnectionError)

        def invoke(self, **kwargs):
            return {
                "Payload": BytesIO(json.dumps(response).encode()),
                "ResponseMetadata": {"RequestId": "lambda-request"},
            }

    sdk = SimpleNamespace(client=lambda *args, **kwargs: Client())
    tools = LambdaTools(
        sdk, {"get_recent_logs": "allowed-arn"}, request(), lambda *args, **kwargs: None
    )
    with pytest.raises(error):
        tools.invoke(tool_call("get_recent_logs"), timeout_seconds=10)
    with pytest.raises(ToolFailure):
        tools.invoke(tool_call("retrieve_runbook"), timeout_seconds=10)
