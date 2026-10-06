"""Controlled controller faults with REAL Guardrails and OFFLINE model/tool doubles."""

import json

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.records import Evidence
from incident_demo.corpus import load_fixture, load_knowledge
from incident_demo.investigator.engine import Engine
from incident_demo.investigator.providers import FixtureTools, OfflineProvider
from incident_demo.live.guardrails import GuardrailPolicy


def verify(sdk, outputs, audit, root):
    return [
        verify_one(sdk, outputs, audit, root, target, unavailable)
        for target in ("input", "source", "output")
        for unavailable in (False, True)
    ]


def verify_one(sdk, outputs, audit, root, target, unavailable):
    secret = "DEMO_CANARY_CONTROLLEDPROBE"
    fixture = load_fixture(root / "fixtures/cases/case-001.json")
    normal = GuardrailPolicy(
        sdk, outputs["GuardrailIdOutput"], outputs["GuardrailVersionOutput"], audit
    )
    missing = GuardrailPolicy(sdk, outputs["GuardrailIdOutput"], "999999", audit)

    class Boundary:
        def check(self, name, text):
            return (missing if unavailable and name == target else normal).check(name, text)

    class Tools:
        def __init__(self):
            self.base = FixtureTools(fixture, load_knowledge(root))

        def invoke(self, call, *, timeout_seconds):
            evidence = self.base.invoke(call, timeout_seconds=timeout_seconds)
            if target == "source" and not unavailable and call.name == "get_recent_changes":
                data = evidence[0].model_dump(mode="json")
                data["payload"]["items"][0]["summary"] = secret
                data["content_hash"] = content_hash(data["payload"])
                return (Evidence.model_validate_json(json.dumps(data)),)
            return evidence

    class Provider:
        def respond(self, request, *, timeout_seconds):
            raw = json.loads(OfflineProvider().respond(request, timeout_seconds=timeout_seconds))
            if target == "output" and not unavailable:
                raw["investigation"]["justification"] = secret
            return json.dumps(raw)

    incident = fixture.incident
    if target == "input" and not unavailable:
        incident = incident.model_copy(update={"summary": secret})
    engine = Engine(root, "V0", incident, Provider(), Tools(), policy=Boundary())
    result = engine.run()
    expected = "filter_unavailable" if unavailable else "filter_blocked"
    if result.stop_reason != expected or secret in result.model_dump_json():
        raise ValueError("controller boundary did not fail closed or leaked the canary")
    if target != "output" and result.provider_calls:
        raise ValueError("blocked source reached the model")
    return {
        "mode": "real_guardrails_offline_model_and_tools",
        "target": target,
        "unavailable": unavailable,
        "stop_reason": result.stop_reason,
        "status": result.status,
        "provider_calls": result.provider_calls,
        "tool_calls": result.usage.tool_calls,
        "canary_retained": False,
    }
