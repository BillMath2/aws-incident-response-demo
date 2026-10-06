"""Read-only Lambda handler. Only packaged synthetic observations are accessible."""

import json
import os
from datetime import timedelta
from pathlib import Path

from pydantic import TypeAdapter

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.records import Evidence
from incident_demo.corpus import ToolResponse
from incident_demo.live.contracts import DiagnosticRequest
from incident_demo.local_tools import sanitized_evidence

RESPONSES = TypeAdapter(tuple[ToolResponse, ...])


def diagnose(request: DiagnosticRequest, catalog: dict, allowed_tool: str):
    if request.call.name != allowed_tool or allowed_tool == "retrieve_runbook":
        raise ValueError("tool not allowed by this function")
    record = catalog[request.telemetry_id]
    responses = RESPONSES.validate_json(json.dumps(record["responses"]))
    matches = [
        r
        for r in responses
        if (r.source if r.status == "error" else r.evidence.source) == allowed_tool
    ]
    if not matches:
        return {"status": "error", "retryable": False}
    response = matches[min(request.attempt - 1, len(matches) - 1)]
    if response.status == "error":
        return {"status": "error", "retryable": response.retryable}
    evidence = sanitized_evidence(response.evidence)
    payload = evidence.payload
    if allowed_tool == "get_recent_changes":
        cutoff = evidence.collected_at - timedelta(minutes=request.call.arguments.window_minutes)
        payload = payload.model_copy(
            update={"items": tuple(c for c in payload.items if c.changed_at >= cutoff)}
        )
    if allowed_tool == "get_recent_logs":
        selected = payload.entries
        if request.call.arguments.filter != "errors":
            needle = request.call.arguments.filter
            selected = tuple(e for e in selected if needle in e.message.lower())
        truncated = payload.truncated or len(selected) > request.call.arguments.limit
        payload = payload.model_copy(
            update={"entries": selected[: request.call.arguments.limit], "truncated": truncated}
        )
    evidence = Evidence.model_validate_json(
        evidence.model_copy(
            update={
                "payload": payload,
                "content_hash": content_hash(payload),
                "complete": evidence.complete and not getattr(payload, "truncated", False),
            }
        ).model_dump_json()
    )
    return {"status": "ok", "evidence": evidence.model_dump(mode="json")}


def handler(event, context):
    request = DiagnosticRequest.model_validate_json(json.dumps(event))
    catalog = json.loads(Path("telemetry.json").read_text())
    result = diagnose(request, catalog, os.environ["TOOL_NAME"])
    print(
        json.dumps(
            {
                "event": "diagnostic",
                "run_id": request.run_id,
                "tool": request.call.name,
                "attempt": request.attempt,
                "status": result["status"],
                "aws_request_id": context.aws_request_id,
            }
        )
    )
    return result
