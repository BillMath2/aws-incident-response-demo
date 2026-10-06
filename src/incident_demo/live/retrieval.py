"""Retrieve only frozen, hash-verified passages through the real Bedrock KB API."""

import hashlib
import json
from pathlib import Path

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.records import Evidence
from incident_demo.contracts.tools import CALL_ADAPTER, Passage
from incident_demo.investigator.providers import ToolFailure
from incident_demo.live.clients import sdk_config

PREFIX = "knowledge/p06-v1/"


def corpus_manifest(root: Path):
    """Package provenance only, never local passage text or evaluator answers."""
    catalog = json.loads((root / "knowledge/catalog.json").read_text())
    result = {}
    for entry in catalog["documents"]:
        data = (root / entry["path"]).read_bytes().replace(b"\r\n", b"\n")
        passage = entry["passage"]
        if (
            hashlib.sha256(data).hexdigest() != entry["sha256"]
            or data.decode() != passage["excerpt"]
        ):
            raise ValueError("frozen runbook changed")
        metadata = {k: v for k, v in passage.items() if k not in {"kind", "excerpt"}}
        metadata["sha256"] = entry["sha256"]
        metadata["corpus_version"] = catalog["corpus_version"]
        if len(json.dumps(metadata).encode()) > 1024:
            raise ValueError("S3 Vectors custom metadata exceeds 1 KiB")
        result[passage["passage_id"]] = {
            "metadata": metadata,
            "key": PREFIX + Path(entry["path"]).name,
            "text_sha256": hashlib.sha256(data.decode().strip().encode()).hexdigest(),
        }
    return result


class KnowledgeTools:
    def __init__(self, sdk, diagnostics, request, audit, kb_id, bucket, manifest):
        self.client = sdk.client("bedrock-agent-runtime", config=sdk_config(20))
        self.diagnostics, self.request, self.audit = diagnostics, request, audit
        self.kb_id, self.bucket, self.manifest = kb_id, bucket, manifest

    def decode(self, response, limit):
        rows = response.get("retrievalResults", [])
        if response.get("nextToken") or not 1 <= len(rows) <= limit:
            raise ToolFailure("empty, paginated or oversized retrieval")
        evidence, seen = [], set()
        for row in rows:
            metadata = row.get("metadata", {})
            passage_id = metadata.get("passage_id")
            expected = self.manifest.get(passage_id)
            if expected is None or passage_id in seen:
                raise ToolFailure("unknown or duplicate passage")
            if any(metadata.get(k) != v for k, v in expected["metadata"].items()):
                raise ToolFailure("missing or mismatched passage metadata")
            location = row.get("location", {})
            if location.get("type") != "S3" or location.get("s3Location", {}).get("uri") != (
                f"s3://{self.bucket}/{expected['key']}"
            ):
                raise ToolFailure("untrusted document location")
            text = row.get("content", {}).get("text", "")
            # The no-chunking parser may trim outer whitespace. No other normalization
            # is allowed; compare against a separately pinned trimmed-content digest.
            if hashlib.sha256(text.strip().encode()).hexdigest() != expected["text_sha256"]:
                raise ToolFailure("retrieved text differs from frozen corpus")
            payload = Passage.model_validate_json(
                json.dumps(
                    {
                        "kind": "runbook",
                        "excerpt": text.strip(),
                        **{
                            k: v
                            for k, v in expected["metadata"].items()
                            if k not in {"sha256", "corpus_version"}
                        },
                    }
                )
            )
            evidence.append(
                Evidence(
                    evidence_id="kb-" + passage_id,
                    source="retrieve_runbook",
                    # Fixed per investigation so repeated retrieval cannot create ID collisions.
                    collected_at=self.request.incident.submitted_at,
                    source_version="kb-corpus-1.0.0",
                    complete=True,
                    sanitized=True,
                    payload=payload,
                    content_hash=content_hash(payload),
                )
            )
            seen.add(passage_id)
        return tuple(evidence)

    def invoke(self, call, *, timeout_seconds):
        call = CALL_ADAPTER.validate_json(call.model_dump_json())
        if call.name != "retrieve_runbook":
            return self.diagnostics.invoke(call, timeout_seconds=timeout_seconds)
        if timeout_seconds <= 0:
            raise TimeoutError()
        self.audit("retrieval_started", knowledge_base_id=self.kb_id)
        response = self.client.retrieve(
            knowledgeBaseId=self.kb_id,
            retrievalQuery={"text": call.arguments.query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": call.arguments.limit,
                    "overrideSearchType": "SEMANTIC",
                    "filter": {
                        "andAll": [
                            {"equals": {"key": "service_id", "value": call.arguments.service_id}},
                            {"equals": {"key": "corpus_version", "value": "1.0.0"}},
                        ]
                    },
                }
            },
        )
        result = self.decode(response, call.arguments.limit)
        self.audit(
            "retrieval_finished",
            knowledge_base_id=self.kb_id,
            request_id=response["ResponseMetadata"]["RequestId"],
            passages=[
                {
                    "id": e.payload.passage_id,
                    "status": e.payload.status,
                    "sha256": e.content_hash,
                    "score": row.get("score"),
                }
                for e, row in zip(result, response["retrievalResults"], strict=True)
            ],
        )
        return result
