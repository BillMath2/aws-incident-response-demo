"""Durable control plane. Stored documents, not caller payloads, authorize actions."""

import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field

from incident_demo.contracts.base import Contract, Digest, Identifier, content_hash
from incident_demo.contracts.records import ActionReceipt, Proposal, RollbackArguments, ServiceState


class Conflict(ValueError):
    """A conditional write or control precondition rejected this request."""


class Intake(Contract):
    idempotency_key: Identifier
    scenario: Literal["investigate", "control-recovery", "control-unresolved", "control-expiry"]


class Decision(Contract):
    proposal_hash: Digest
    decision: Literal["approved", "rejected"]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    facts_reviewed: Literal[True]
    citations_reviewed: Literal[True]


def now():
    return datetime.now(UTC)


def actor_identity(event, allowed_role):
    """Only API Gateway's signed IAM context supplies identity; sessions share role identity."""
    iam = event.get("requestContext", {}).get("authorizer", {}).get("iam", {})
    arn = iam.get("userArn", "")
    account = allowed_role.split(":")[4]
    role = allowed_role.split("role/", 1)[1]
    if not re.fullmatch(rf"arn:aws:sts::{account}:assumed-role/{re.escape(role)}/[^/]+", arn):
        raise PermissionError("wrong signed role")
    return allowed_role, arn


def public(record):
    """Explicit response allowlist. Callback tokens are never public fields."""
    result = {
        k: record[k]
        for k in ("run_id", "scenario", "status", "proposal", "artifact", "verification", "history")
        if k in record
    }
    if "proposal" in result:
        result["approval_id"] = "approval-" + record["run_id"]
    return result


def advance(record, status, at, **fields):
    return (
        record
        | fields
        | {
            "status": status,
            "history": record.get("history", []) + [{"status": status, "at": at.isoformat()}],
        }
    )


class Control:
    """Repository commits compare all versions atomically, including receipt absence."""

    def __init__(self, repository, clock=now):
        self.db, self.clock = repository, clock

    def intake(self, request, principal, session_arn):
        digest = content_hash(request)
        run_id = (
            "p07-" + sha256((principal + ":" + request.idempotency_key).encode()).hexdigest()[:40]
        )
        key = "request#" + run_id
        old = self.db.get("runs", key)
        if old:
            if old["payload_hash"] != digest:
                raise Conflict("idempotency key reused with different payload")
            return self.db.get("runs", "run#" + run_id)
        at = self.clock()
        batch_key = "batch#p07-dev-01"
        batch = self.db.get("runs", batch_key)
        counts = batch or {"accepted": 0, "live": 0}
        live = int(request.scenario == "investigate")
        if counts["accepted"] >= 32 or counts["live"] + live > 3:
            raise Conflict("P07 batch intake allowance exhausted")
        run = advance(
            {
                "run_id": run_id,
                "scenario": request.scenario,
                "principal": principal,
                "session_arn": session_arn,
            },
            "pending",
            at,
        )
        try:
            self.db.commit(
                [
                    (
                        "runs",
                        batch_key,
                        batch,
                        {"accepted": counts["accepted"] + 1, "live": counts["live"] + live},
                    ),
                    ("runs", key, None, {"payload_hash": digest, "run_id": run_id}),
                    ("runs", "run#" + run_id, None, run),
                    (
                        "runs",
                        "dispatch#" + run_id,
                        None,
                        {"run_id": run_id, "attempts": 0, "status": "pending", "next_at": 0},
                    ),
                    (
                        "sandbox",
                        "service#" + run_id,
                        None,
                        {"service_id": "checkout-api", "release": "release-42", "revision": 0},
                    ),
                ]
            )
        except Conflict:
            old = self.db.get("runs", key)
            if not old or old["payload_hash"] != digest:
                raise
        return self.db.get("runs", "run#" + run_id)

    def propose(self, run_id, evidence_ids, artifact):
        run = self.db.get("runs", "run#" + run_id)
        if run["status"] == "proposal_ready":
            return run
        if run["status"] != "investigating":
            raise Conflict("investigation is not active")
        at = self.clock()
        seconds = 30 if run["scenario"] == "control-expiry" else 900
        proposal = Proposal.create(
            proposal_id="proposal-" + run_id,
            run_id=run_id,
            action="rollback_demo_release",
            arguments=RollbackArguments(service_id="checkout-api", target_release="release-41"),
            expected_current_release="release-42",
            evidence_ids=tuple(evidence_ids),
            created_at=at,
            expires_at=at + timedelta(seconds=seconds),
        )
        updated = advance(
            run, "proposal_ready", at, proposal=proposal.model_dump(mode="json"), artifact=artifact
        )
        self.db.commit([("runs", "run#" + run_id, run, updated)])
        return updated

    def wait(self, run_id, token):
        run = self.db.get("runs", "run#" + run_id)
        p = Proposal.model_validate_json(json.dumps(run["proposal"]))
        old = self.db.get("approvals", run_id)
        if old:
            # Callback task has no retry: a new token must never replace an accepted decision.
            if old["token"] != token:
                raise Conflict("callback already registered")
            return
        if run["status"] != "proposal_ready" or self.clock() >= p.expires_at:
            raise Conflict("proposal is not available for approval")
        self.db.commit(
            [
                ("runs", "run#" + run_id, run, advance(run, "awaiting_approval", self.clock())),
                (
                    "approvals",
                    run_id,
                    None,
                    {
                        "run_id": run_id,
                        "approval_id": "approval-" + run_id,
                        "proposal_id": p.proposal_id,
                        "authorized_service": p.arguments.service_id,
                        "token": token,
                        "status": "waiting",
                        "proposal_hash": p.proposal_hash,
                        "expires": int(p.expires_at.timestamp()),
                        "callback": "pending",
                    },
                ),
            ]
        )

    def decide(self, run_id, decision, principal, session_arn):
        run = self.db.get("runs", "run#" + run_id)
        approval = self.db.get("approvals", run_id)
        if not run or not approval:
            raise Conflict("run is not awaiting approval")
        fingerprint = content_hash(
            {"decision": decision.model_dump(mode="json"), "principal": principal}
        )
        if approval.get("decision_hash") == fingerprint:
            return approval
        p = Proposal.model_validate_json(json.dumps(run["proposal"]))
        if (
            approval["status"] != "waiting"
            or run["status"] != "awaiting_approval"
            or self.clock() >= p.expires_at
            or decision.proposal_hash != p.proposal_hash
            or approval["proposal_hash"] != p.proposal_hash
            or approval["proposal_id"] != p.proposal_id
            or approval["authorized_service"] != p.arguments.service_id
        ):
            raise Conflict("stale, conflicting or mismatched decision")
        updated = approval | {
            "status": decision.decision,
            "decision_hash": fingerprint,
            "actor": principal,
            "session_arn": session_arn,
            "decision": decision.model_dump(mode="json"),
            "decided_at": self.clock().isoformat(),
        }
        self.db.commit(
            [("runs", "run#" + run_id, run, None), ("approvals", run_id, approval, updated)]
        )
        return updated

    def execute(self, run_id, approver_role):
        old = self.db.get("sandbox", "receipt#" + run_id)
        if old:
            return old["receipt"]
        run = self.db.get("runs", "run#" + run_id)
        approval = self.db.get("approvals", run_id)
        service = self.db.get("sandbox", "service#" + run_id)
        p = Proposal.model_validate_json(json.dumps(run["proposal"]))
        at = self.clock()
        if (
            run["status"] != "awaiting_approval"
            or not approval
            or approval["status"] != "approved"
            or approval.get("actor") != approver_role
            or approval["proposal_hash"] != p.proposal_hash
            or approval["proposal_id"] != p.proposal_id
            or approval["authorized_service"] != p.arguments.service_id
            or at >= p.expires_at
            or at.timestamp() >= approval["expires"]
            or service["release"] != p.expected_current_release
        ):
            raise Conflict("executor preconditions failed")
        before = ServiceState(**{k: service[k] for k in ("service_id", "release", "revision")})
        after = ServiceState(
            service_id=before.service_id, release="release-41", revision=before.revision + 1
        )
        receipt = ActionReceipt(
            receipt_id="receipt-" + run_id,
            idempotency_key=run_id,
            proposal_id=p.proposal_id,
            proposal_hash=p.proposal_hash,
            before=before,
            after=after,
            status="applied",
            audited_at=at,
        ).model_dump(mode="json")
        try:
            self.db.commit(
                [
                    ("runs", "run#" + run_id, run, None),
                    ("approvals", run_id, approval, approval | {"status": "consumed"}),
                    ("sandbox", "service#" + run_id, service, after.model_dump(mode="json")),
                    ("sandbox", "receipt#" + run_id, None, {"receipt": receipt}),
                ]
            )
        except Conflict:
            old = self.db.get("sandbox", "receipt#" + run_id)
            if not old:
                raise
            return old["receipt"]
        return receipt

    def finish(self, run_id, status, **fields):
        run = self.db.get("runs", "run#" + run_id)
        if run["status"] in {
            "resolved",
            "unresolved",
            "rejected",
            "expired",
            "failed",
            "escalated",
        }:
            return public(run)
        approval = self.db.get("approvals", run_id)
        receipt = self.db.get("sandbox", "receipt#" + run_id)
        if receipt and status not in {"resolved", "unresolved"}:
            status = "unresolved"
        changes = [("runs", "run#" + run_id, run, advance(run, status, self.clock(), **fields))]
        if approval:
            # A race with execution is resolved by the same approval version CAS.
            closed = {k: v for k, v in approval.items() if k != "token"}
            changes.append(
                (
                    "approvals",
                    run_id,
                    approval,
                    closed
                    | {"status": approval["status"] if receipt else "closed", "callback": "closed"},
                )
            )
        self.db.commit(changes)
        return public(self.db.get("runs", "run#" + run_id))
