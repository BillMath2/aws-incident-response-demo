"""Actual Bedrock via LangChain and allowlisted synchronous Lambda diagnostics."""

import json
import time

from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from incident_demo.contracts.base import canonical_json, content_hash
from incident_demo.contracts.experiments import DECISION_ADAPTER, SearchReply
from incident_demo.contracts.records import Evidence, Investigation
from incident_demo.contracts.tools import ChangesArgs, HealthArgs, LogsArgs
from incident_demo.investigator.providers import ToolFailure, TransientFailure
from incident_demo.live.clients import sdk_config


def response_phase(request):
    collected = {item.source for item in request.evidence}
    if (
        request.phase == "decide"
        and {"get_service_health", "get_recent_changes", "get_recent_logs"} <= collected
    ):
        return "final"
    return request.phase


def inline_schema(schema):
    """Render trusted contract references inline for Nova; validation stays unchanged."""
    definitions = schema.get("$defs", {})

    def render(value):
        if isinstance(value, list):
            return [render(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            name = value["$ref"].removeprefix("#/$defs/")
            value = {**definitions[name], **{k: v for k, v in value.items() if k != "$ref"}}
        return {
            k: render(v) for k, v in value.items() if k not in {"$defs", "discriminator", "title"}
        }

    return render(schema)


def response_tools(request):
    phase = response_phase(request)
    finish = Investigation.model_json_schema()
    if request.variant == "V2":
        finish["properties"]["selected_candidate_id"] = {"type": "string"}
    definitions = (
        [
            (
                "submit_search",
                "Report the bounded hypothesis-search step",
                SearchReply.model_json_schema(),
            )
        ]
        if phase in {"seed", "update"}
        else [
            (
                "finish_investigation",
                "Finish with cited facts and an escalation or incomplete outcome",
                finish,
            )
        ]
    )
    if phase == "decide":
        definitions += [
            (
                "get_service_health",
                "Read the immutable service health snapshot",
                HealthArgs.model_json_schema(),
            ),
            (
                "get_recent_changes",
                "Read the immutable recent deployment/configuration snapshot",
                ChangesArgs.model_json_schema(),
            ),
            (
                "get_recent_logs",
                "Read the immutable diagnostic logs snapshot",
                LogsArgs.model_json_schema(),
            ),
        ]
    tools = []
    for name, description, schema in definitions:
        expanded = inline_schema(schema)
        # Nova v1 permits only these three top-level schema keys. The original
        # Pydantic contracts still enforce every constraint after generation.
        parameters = {k: expanded[k] for k in ("type", "properties", "required")}
        tools.append(
            {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            }
        )
    return tools


def decode_response(reply, request, tools):
    if (
        reply.response_metadata.get("stopReason") != "tool_use"
        or not 1 <= len(reply.tool_calls) <= 4
    ):
        raise ValueError("expected a bounded complete native tool decision")
    decisions = [decode_call(call, request, tools) for call in reply.tool_calls]
    # Only the first validated decision reaches the sequential ReAct controller.
    # Other suggestions are not executed or queued; the next turn sees new evidence.
    return decisions[0]


def decode_call(call, request, tools):
    if call["name"] not in {tool["function"]["name"] for tool in tools}:
        raise ValueError("model selected an unavailable tool")
    arguments = dict(call["args"])
    if call["name"] == "finish_investigation":
        selected = arguments.pop("selected_candidate_id", None) if request.variant == "V2" else None
        decision = {"kind": "finish", "investigation": arguments, "selected_candidate_id": selected}
    elif call["name"] == "submit_search":
        decision = arguments
    else:
        decision = {
            "kind": "tool",
            "call": {"name": call["name"], "arguments": arguments},
            "purpose": "Collect observations with " + call["name"],
        }
    encoded = canonical_json(decision)
    DECISION_ADAPTER.validate_json(encoded)
    return encoded


class CountedClient:
    """Preflight exact tokens when supported; fail closed on all other API errors.

    Nova v1 rejects CountTokens. For those two pinned models only, use a 32 KiB
    wire limit and reserve the entire 300K model context, not a token estimate.
    """

    def __init__(self, client, audit, usage):
        self.client, self.audit, self.usage = client, audit, usage

    def converse(self, **kwargs):
        counted = {
            key: kwargs[key] for key in ("messages", "system", "toolConfig") if key in kwargs
        }
        wire_bytes = len(canonical_json(counted).encode())
        if wire_bytes > 32768:
            raise ValueError("input byte cap exceeded")
        count = None
        try:
            count = self.client.count_tokens(
                modelId=kwargs["modelId"], input={"converse": counted}
            )["inputTokens"]
        except self.client.exceptions.ValidationException as exc:
            unsupported = "doesn't support counting tokens" in str(exc)
            if not unsupported or kwargs["modelId"] not in {
                "us.amazon.nova-lite-v1:0",
                "us.amazon.nova-pro-v1:0",
            }:
                raise
            self.audit(
                "token_count_unsupported", reserved_input_tokens=300000, input_bytes=wire_bytes
            )
        if count is not None and count > 6000:
            self.audit("input_limit", input_tokens=count)
            raise ValueError("input token cap exceeded")
        if kwargs["inferenceConfig"]["maxTokens"] > 1500:
            raise ValueError("output token cap exceeded")
        self.usage["model_calls"] += 1
        self.audit("model_started", input_tokens=count)
        response = self.client.converse(**kwargs)
        usage = response["usage"]
        self.usage["input_tokens"] += usage["inputTokens"]
        self.usage["output_tokens"] += usage["outputTokens"]
        self.audit(
            "model_finished",
            input_tokens=usage["inputTokens"],
            output_tokens=usage["outputTokens"],
            request_id=response["ResponseMetadata"]["RequestId"],
        )
        if usage["inputTokens"] > 6000:
            raise ValueError("observed input exceeds planning target; no further calls")
        return response


class BedrockProvider:
    def __init__(self, session, model_id, audit):
        self.model_id, self.audit = model_id, audit
        self.client = session.client("bedrock-runtime", config=sdk_config(25))
        self.usage = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}

    def respond(self, request, *, timeout_seconds):
        # The enclosing worker has a killable hard deadline, in addition to SDK timeouts.
        if timeout_seconds <= 0:
            raise TimeoutError()
        payload = {
            "run_id": request.run_id,
            "phase": request.phase,
            "round": request.round,
            "incident": request.incident.model_dump(mode="json"),
            "evidence": [e.model_dump(mode="json") for e in request.evidence],
            "branches": [b.model_dump(mode="json") for b in request.branches],
            "remaining_model_calls": request.remaining_model_calls,
            "remaining_tool_calls": request.remaining_tool_calls,
        }
        system = (
            request.system_prompt + "\nP05: retrieval and Bedrock Guardrails are NOT configured. "
        )
        system += (
            "Use the three diagnostic tools only. "
            "Collect health, changes and logs before concluding. "
        )
        system += "Escalate or report incomplete; current rollback guidance is unavailable. "
        phase = response_phase(request)
        if phase == "final" and request.phase == "decide":
            system += (
                "All three available diagnostic snapshots have been collected. They are immutable; "
                "repeating a tool cannot refresh them. Return a finish decision now, with cited "
                "facts, uncertainty and an escalation or incomplete outcome. "
            )
        system += (
            "Use exactly one provided native response tool per turn. Do not output a JSON text "
            "response or private reasoning. Diagnostic arguments follow their tool schema; "
            "finish_investigation submits the final investigation without running any action. "
        )
        tools = response_tools(request)
        self.audit(
            "prompt_built",
            adapter_prompt_version="p05-v7-native",
            response_phase=phase,
            system_sha256=content_hash(system),
            tool_schema_sha256=content_hash(tools),
        )
        model = ChatBedrockConverse(
            model_id=self.model_id,
            provider="amazon",
            region_name="us-east-2",
            client=CountedClient(self.client, self.audit, self.usage),
            max_tokens=request.max_output_tokens,
            temperature=0,
            disable_streaming=True,
            supports_tool_choice_values=("auto", "any", "tool"),
        )
        try:
            reply = model.bind_tools(tools, tool_choice="any").invoke(
                [SystemMessage(system), HumanMessage(canonical_json(payload))],
                config={"callbacks": []},
            )
        except (
            self.client.exceptions.ThrottlingException,
            self.client.exceptions.ServiceUnavailableException,
            self.client.exceptions.InternalServerException,
        ) as exc:
            raise TransientFailure() from exc
        except (
            ReadTimeoutError,
            ConnectTimeoutError,
            self.client.exceptions.ModelTimeoutException,
        ) as exc:
            raise TimeoutError() from exc
        try:
            self.audit(
                "native_response",
                stop_reason=reply.response_metadata.get("stopReason"),
                proposed_decisions=len(reply.tool_calls),
                unused_decisions=max(0, len(reply.tool_calls) - 1),
            )
            return decode_response(reply, request, tools)
        except ValidationError as exc:
            self.audit(
                "model_output_invalid",
                error_types=sorted({e["type"] for e in exc.errors(include_input=False)}),
            )
            raise


class LambdaTools:
    def __init__(self, session, functions, request, audit):
        self.client = session.client("lambda", config=sdk_config(10))
        self.functions, self.request, self.audit = functions, request, audit
        self.attempts = {}

    def invoke(self, call, *, timeout_seconds):
        if call.name not in self.functions or timeout_seconds <= 0:
            raise ToolFailure()
        attempt = self.attempts.get(call.name, 0) + 1
        self.attempts[call.name] = attempt
        payload = {
            "run_id": self.request.run_id,
            "telemetry_id": self.request.telemetry_id,
            "attempt": attempt,
            "call": call.model_dump(mode="json"),
        }
        self.audit("lambda_started", tool=call.name, attempt=attempt)
        started = time.monotonic()
        try:
            response = self.client.invoke(
                FunctionName=self.functions[call.name],
                InvocationType="RequestResponse",
                Payload=canonical_json(payload).encode(),
            )
            with response["Payload"] as body:
                raw = body.read(65537)
        except self.client.exceptions.TooManyRequestsException as exc:
            raise TransientFailure() from exc
        except (ReadTimeoutError, ConnectTimeoutError) as exc:
            raise TimeoutError() from exc
        self.audit(
            "lambda_finished",
            tool=call.name,
            attempt=attempt,
            latency_ms=int((time.monotonic() - started) * 1000),
            request_id=response["ResponseMetadata"]["RequestId"],
        )
        if response.get("FunctionError") or len(raw) > 65536:
            raise ToolFailure()
        result = json.loads(raw)
        if result["status"] == "error":
            if result["retryable"]:
                raise TransientFailure()
            raise ToolFailure()
        return (Evidence.model_validate_json(json.dumps(result["evidence"])),)
