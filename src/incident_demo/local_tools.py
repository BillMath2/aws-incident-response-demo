"""Read-only fixture diagnostics and an independent, synthetic health observer."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from incident_demo.contracts.base import Contract, content_hash
from incident_demo.contracts.local import ToolAttempt
from incident_demo.contracts.records import Evidence
from incident_demo.contracts.tools import CALL_ADAPTER, Health
from incident_demo.corpus import Fixture, KnowledgeCatalog, ToolError


def sanitize(text: str) -> str:
    """Small demo-canary/terminal-control scrubber, not a general secret detector."""
    text = re.sub(r"DEMO_CANARY_[A-Za-z0-9_-]+", "[SYNTHETIC_CANARY_REDACTED]", text)
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)


def sanitized_evidence(item: Evidence) -> Evidence:
    data = item.model_dump(mode="json")
    if item.payload.kind == "logs":
        for entry in data["payload"]["entries"]:
            entry["message"] = sanitize(entry["message"])
    elif item.payload.kind == "changes":
        for entry in data["payload"]["items"]:
            entry["summary"] = sanitize(entry["summary"])
    elif item.payload.kind == "runbook":
        data["payload"]["excerpt"] = sanitize(data["payload"]["excerpt"])
    data["content_hash"] = content_hash(data["payload"])
    # Wire validation also verifies source/result type, hash and payload bounds.
    return Evidence.model_validate_json(json.dumps(data))


def gather(fixture: Fixture, catalog: KnowledgeCatalog, now: datetime):
    """Fixed diagnostics, one retry per transient operation, then one fixture retrieval."""
    evidence: list[Evidence] = []
    attempts: list[ToolAttempt] = []
    missing: list[str] = []
    for name in ("get_service_health", "get_recent_changes", "get_recent_logs"):
        CALL_ADAPTER.validate_python({"name": name, "arguments": {"service_id": "checkout-api"}})
        responses = [
            r
            for r in fixture.responses
            if (r.source if r.status == "error" else r.evidence.source) == name
        ]
        for attempt in (1, 2):
            response = (
                responses[attempt - 1]
                if len(responses) >= attempt
                else ToolError(
                    status="error", source=name, code="persistent_unavailable", retryable=False
                )
            )
            if response.status == "ok":
                item = sanitized_evidence(response.evidence)
                evidence.append(item)
                attempts.append(
                    ToolAttempt(
                        name=name, attempt=attempt, status="ok", evidence_ids=(item.evidence_id,)
                    )
                )
                break
            attempts.append(
                ToolAttempt(name=name, attempt=attempt, status="error", error_code=response.code)
            )
            if not response.retryable or attempt == 2:
                missing.append(f"{name} unavailable after {attempt} attempt(s)")
                break
    CALL_ADAPTER.validate_python(
        {
            "name": "retrieve_runbook",
            "arguments": {
                "service_id": "checkout-api",
                "query": "checkout incident rollback policy",
                "limit": 5,
            },
        }
    )
    passages = {entry.passage.passage_id: entry.passage for entry in catalog.documents}
    retrieved: list[Evidence] = []
    for passage_id in fixture.retrieval_passage_ids:
        if passage_id not in passages:
            missing.append("Requested runbook passage is unavailable")
            continue
        passage = passages[passage_id]
        retrieved.append(
            sanitized_evidence(
                Evidence(
                    evidence_id=passage_id,
                    source="retrieve_runbook",
                    collected_at=now,
                    source_version=passage.version,
                    content_hash=content_hash(passage),
                    complete=True,
                    sanitized=True,
                    payload=passage,
                )
            )
        )
    evidence.extend(retrieved)
    attempts.append(
        ToolAttempt(
            name="retrieve_runbook",
            attempt=1,
            status="error" if not retrieved else "ok",
            error_code="missing_passage" if not retrieved else None,
            evidence_ids=tuple(e.evidence_id for e in retrieved),
        )
    )
    return tuple(evidence), tuple(attempts), tuple(missing)


class VerificationProfile(Contract):
    release: Literal["release-41", "release-42"]
    error_rate: float
    latency_p95_ms: float
    dependency_state: Literal["healthy", "degraded", "unknown"]


class VerificationFixtures(Contract):
    version: Literal["1.0.0"]
    recovered: VerificationProfile
    unhealthy: VerificationProfile


def observe_health(root: Path, profile: str, now: datetime, evidence_id: str) -> Evidence | None:
    """Separate fixture measurement; the action receipt does not determine its values."""
    if profile == "missing":
        return None
    if profile not in {"recovered", "unhealthy"}:
        raise ValueError("unknown verification profile")
    config = VerificationFixtures.model_validate_json(
        (root / "fixtures/local-verification.json").read_bytes()
    )
    values = getattr(config, profile)
    health = Health(
        kind="health", service_id="checkout-api", observed_at=now, **values.model_dump()
    )
    return Evidence(
        evidence_id=evidence_id,
        source="get_service_health",
        collected_at=now,
        source_version=f"local-verification-{config.version}-{profile}",
        content_hash=content_hash(health),
        complete=True,
        sanitized=True,
        payload=health,
    )
