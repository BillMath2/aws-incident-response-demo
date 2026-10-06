"""Fail-closed, numbered-policy checks; never persist content or matched values."""

from incident_demo.live.clients import sdk_config

MAX_CHECKS = 47  # input + eight tools * five passages + six model outputs
MAX_BYTES = 32768


class GuardrailPolicy:
    def __init__(self, sdk, identifier, version, audit):
        if not version.isdigit() or int(version) < 1:
            raise ValueError("a numbered immutable guardrail version is required")
        self.client = sdk.client("bedrock-runtime", config=sdk_config(15))
        self.identifier, self.version, self.audit = identifier, version, audit
        self.calls = 0

    def check(self, boundary, text):
        if boundary not in {"input", "source", "output"}:
            raise ValueError("unknown boundary")
        if not text or len(text.encode()) > MAX_BYTES or self.calls >= MAX_CHECKS:
            raise ValueError("guardrail work bound exceeded")
        self.calls += 1
        fields = {
            "boundary": boundary,
            "guardrail_id": self.identifier,
            "guardrail_version": self.version,
            "call": self.calls,
        }
        self.audit("guardrail_started", **fields)
        try:
            response = self.client.apply_guardrail(
                guardrailIdentifier=self.identifier,
                guardrailVersion=self.version,
                source="OUTPUT" if boundary == "output" else "INPUT",
                content=[{"text": {"text": text, "qualifiers": ["guard_content"]}}],
                outputScope="INTERVENTIONS",
            )
            action = response["action"]
            coverage = response["guardrailCoverage"]["textCharacters"]
            if action not in {"NONE", "GUARDRAIL_INTERVENED"} or (
                coverage["guarded"] != coverage["total"] or coverage["total"] < len(text)
            ):
                raise ValueError("missing or partial guardrail coverage")
        except Exception as exc:
            self.audit("guardrail_unavailable", **fields, category=type(exc).__name__)
            raise
        self.audit(
            "guardrail_finished",
            **fields,
            action=action,
            coverage=coverage,
            usage=response["usage"],
            request_id=response["ResponseMetadata"]["RequestId"],
        )
        return action == "NONE"
