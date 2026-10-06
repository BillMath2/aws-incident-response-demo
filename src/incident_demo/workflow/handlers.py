"""Private Lambda entry points. Every function has a distinct execution role."""

import json
import os
from datetime import datetime, timedelta
from functools import lru_cache
from types import SimpleNamespace

import boto3
from botocore.config import Config
from pydantic import ValidationError

from incident_demo.contracts.base import content_hash
from incident_demo.contracts.experiments import ExperimentResult
from incident_demo.contracts.records import validate_citations
from incident_demo.investigator.engine import Engine
from incident_demo.live.contracts import LiveRequest
from incident_demo.workflow.durable import (
    Conflict,
    Control,
    Decision,
    Intake,
    actor_identity,
    advance,
    now,
    public,
)
from incident_demo.workflow.repository import Repository


@lru_cache
def client(service):
    return boto3.Session(region_name="us-east-2").client(
        service,
        config=Config(
            connect_timeout=2,
            read_timeout=130 if service == "bedrock-agentcore" else 10,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )


@lru_cache
def control():
    return Control(
        Repository(
            client("dynamodb"),
            {
                name: os.environ[name.upper() + "_TABLE"]
                for name in ("runs", "approvals", "sandbox")
            },
        )
    )


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def artifact(key, document):
    raw = encode(document).encode()
    if len(raw) > 196608:
        raise Conflict("artifact exceeds 192 KiB")
    s3 = client("s3")
    try:
        s3.put_object(
            Bucket=os.environ["BUCKET"],
            Key=key,
            Body=raw,
            ContentType="application/json",
            ServerSideEncryption="AES256",
            IfNoneMatch="*",
        )
    except s3.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] != "PreconditionFailed":
            raise
        previous = read_artifact(key)
        if content_hash(previous) != content_hash(document):
            raise Conflict("immutable artifact differs") from None
    return {"key": key, "sha256": content_hash(document)}


def read_artifact(key):
    objects = client("s3").list_objects_v2(Bucket=os.environ["BUCKET"], Prefix=key, MaxKeys=1)
    if not any(o["Key"] == key for o in objects.get("Contents", [])):
        raise client("s3").exceptions.NoSuchKey(
            {"Error": {"Code": "NoSuchKey", "Message": "No matching immutable artifact"}},
            "GetObject",
        )
    response = client("s3").get_object(Bucket=os.environ["BUCKET"], Key=key)
    with response["Body"] as stream:
        raw = stream.read(196609)
    if len(raw) > 196608:
        raise Conflict("artifact exceeds 192 KiB")
    return json.loads(raw)


def api(event, context):
    response = {"statusCode": 500}
    try:
        response = api_request(event, context)
        return response
    finally:
        request = event.get("requestContext", {})
        # Only trusted routing/authentication metadata is logged, never request/response bodies.
        print(
            encode(
                {
                    "event": "api_request",
                    "request_id": request.get("requestId"),
                    "route": event.get("routeKey"),
                    "status": response["statusCode"],
                    "actor": request.get("authorizer", {}).get("iam", {}).get("userArn"),
                }
            )
        )


def api_request(event, context):
    try:
        route = event["routeKey"]
        expected = (
            "APPROVER_ROLE"
            if route == "POST /runs/{run_id}/decision"
            else ("TESTER_ROLE" if route == "POST /control-tests" else "ANALYST_ROLE")
        )
        # Approvers can read the exact same sanitized proposal view.
        if route == "GET /runs/{run_id}":
            try:
                principal, session = actor_identity(event, os.environ["APPROVER_ROLE"])
            except PermissionError:
                principal, session = actor_identity(event, os.environ["ANALYST_ROLE"])
        else:
            principal, session = actor_identity(event, os.environ[expected])
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded") or len(body.encode()) > 8192:
            raise ValueError("invalid body size or encoding")
        c = control()
        if route in {"POST /incidents", "POST /control-tests"}:
            request = Intake.model_validate_json(body)
            if (request.scenario == "investigate") != (route == "POST /incidents"):
                raise PermissionError("scenario does not match authenticated route")
            result = public(c.intake(request, principal, session))
            status = 202
        else:
            run_id = event["pathParameters"]["run_id"]
            if route == "POST /runs/{run_id}/decision":
                decision = Decision.model_validate_json(body)
                c.decide(run_id, decision, principal, session)
                # Persist first. Scheduled recovery handles a crash or timeout before delivery.
                deliver_callback(run_id)
                result, status = {"run_id": run_id, "decision": decision.decision}, 202
            else:
                run = c.db.get("runs", "run#" + run_id)
                if not run:
                    return {"statusCode": 404, "body": '{"error":"not_found"}'}
                result, status = public(run), 200
                if (event.get("queryStringParameters") or {}).get("review") == "true" and run.get(
                    "artifact"
                ):
                    expected = f"runs/p07/{run_id}/investigation.json"
                    if run["artifact"]["key"] != expected:
                        raise Conflict("unexpected investigation reference")
                    result["investigation"] = read_artifact(expected)
                    if content_hash(result["investigation"]) != run["artifact"]["sha256"]:
                        raise Conflict("investigation artifact hash mismatch")
        return {
            "statusCode": status,
            "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": encode(result),
        }
    except PermissionError:
        return {"statusCode": 403, "body": '{"error":"forbidden"}'}
    except (ValidationError, ValueError, KeyError):
        # Never echo body, credentials, callback token or validation input in errors.
        return {"statusCode": 409, "body": '{"error":"request_rejected"}'}


def dispatch(event, context):
    c = control()
    for key, item in c.db.scan("runs", "dispatch#"):
        if item["status"] != "pending" or item["next_at"] > now().timestamp():
            continue
        run = c.db.get("runs", "run#" + item["run_id"])
        if run["status"] != "pending":
            c.db.commit([("runs", key, item, item | {"status": "delivered"})])
            continue
        if item["attempts"] >= 3:
            # Durable dead-letter record exists even if the external DLQ send is interrupted.
            client("sqs").send_message(
                QueueUrl=os.environ["DLQ_URL"],
                MessageBody=encode({"run_id": item["run_id"], "reason": "dispatch_exhausted"}),
            )
            c.db.commit([("runs", key, item, item | {"status": "dead_letter"})])
            c.finish(item["run_id"], "failed", failure="dispatch_exhausted")
            continue
        leased = item | {"attempts": item["attempts"] + 1, "next_at": int(now().timestamp()) + 60}
        try:
            c.db.commit([("runs", key, item, leased)])
        except Conflict:
            continue
        # Do not mark delivered on publish: the starter acknowledges durable StartExecution.
        response = client("eventbridgev2").put_events(
            EventBusArn=os.environ["BUS_ARN"],
            Entries=[
                {
                    "Source": "incident.demo",
                    "DetailType": "IncidentAccepted",
                    "Detail": encode({"run_id": item["run_id"]}),
                }
            ],
        )
        if response.get("FailedEntryCount", 0):
            raise Conflict("event publish failed; retained outbox will retry")
    return {"recovery": "scanned"}


def starter(event, context):
    # EventBridge v2 RAW transformer forwards the classic PutEvents event envelope.
    if isinstance(event, list):
        if len(event) != 1:
            raise Conflict("unexpected event batch")
        event = event[0]
    run_id = event["detail"]["run_id"]
    c = control()
    dispatch_key = "dispatch#" + run_id
    item = c.db.get("runs", dispatch_key)
    if not item or item["status"] == "dead_letter":
        return {"ignored": True}
    try:
        client("stepfunctions").start_execution(
            stateMachineArn=os.environ["MACHINE_ARN"], name=run_id, input=encode({"run_id": run_id})
        )
    except client("stepfunctions").exceptions.ExecutionAlreadyExists:
        pass  # Names and intake identities are never recycled.
    if item["status"] == "pending":
        try:
            c.db.commit([("runs", dispatch_key, item, item | {"status": "delivered"})])
        except Conflict:
            pass
    return {"run_id": run_id}


def investigate(event, context):
    c, run_id = control(), event["run_id"]
    run = c.db.get("runs", "run#" + run_id)
    if run["status"] == "proposal_ready":
        return {
            "run_id": run_id,
            "proposal_ready": True,
            "wait_seconds": 30 if run["scenario"] == "control-expiry" else 900,
        }
    if run["status"] == "pending":
        c.db.commit([("runs", "run#" + run_id, run, advance(run, "investigating", now()))])
    elif run["status"] != "investigating":
        return {"run_id": run_id, "proposal_ready": False}
    if run["scenario"].startswith("control-"):
        data = {
            "schema": "p07-control-v1",
            "run_id": run_id,
            "synthetic": True,
            "model_generated": False,
            "evidence_id": "control-policy-fixture",
            "detail": "Controlled proposal tests workflow authority, not investigation quality.",
        }
        ref = artifact(f"runs/p07/{run_id}/investigation.json", data)
        c.propose(run_id, [data["evidence_id"]], ref)
    else:
        request = LiveRequest.model_validate_json(
            encode(json.loads(os.environ["LIVE_REQUEST"]) | {"run_id": run_id})
        )
        key = f"runs/p06/{run_id}.json"
        s3 = client("s3")
        try:
            result = read_artifact(key)
        except s3.exceptions.NoSuchKey:
            # Persist an invocation claim before making a billed call. Retry only reads artifacts.
            claim_key = "invocation#" + run_id
            if c.db.get("runs", claim_key):
                raise Conflict(
                    "invocation pending or outcome unknown; no blind reinvocation"
                ) from None
            c.db.commit([("runs", claim_key, None, {"run_id": run_id})])
            runtime = client("bedrock-agentcore")
            try:
                response = runtime.invoke_agent_runtime(
                    agentRuntimeArn=os.environ["RUNTIME_ARN"],
                    qualifier="smoke",
                    runtimeSessionId=run_id,
                    contentType="application/json",
                    payload=request.model_dump_json().encode(),
                )
                with response["response"] as stream:
                    raw = stream.read(196609)
                if len(raw) > 196608:
                    raise Conflict("runtime response too large")
                result = json.loads(raw)
            finally:
                runtime.stop_runtime_session(
                    agentRuntimeArn=os.environ["RUNTIME_ARN"],
                    qualifier="smoke",
                    runtimeSessionId=run_id,
                )
        result.pop("artifact_key", None)
        ref = artifact(f"runs/p07/{run_id}/investigation.json", result)
        if not result.get("usage_complete") or result.get("schema_version") != "p06-v1":
            raise Conflict("runtime envelope incomplete")
        experiment = ExperimentResult.model_validate_json(encode(result["result"]))
        if experiment.run_id != run_id or experiment.mode != "aws_live":
            raise Conflict("runtime identity mismatch")
        validate_citations(experiment.investigation, experiment.evidence)
        if experiment.status != "complete":
            c.finish(run_id, "failed", artifact=ref)
            return {"run_id": run_id, "proposal_ready": False}
        if experiment.investigation.outcome != "propose_rollback":
            c.finish(run_id, "escalated", artifact=ref)
            return {"run_id": run_id, "proposal_ready": False}
        kinds = {e.payload.kind for e in experiment.evidence if e.complete}
        if not {"health", "changes", "logs", "runbook"} <= kinds:
            raise Conflict("missing proposal evidence")
        Engine.check_proposal_preconditions(
            SimpleNamespace(incident=request.incident, evidence=experiment.evidence)
        )
        c.propose(run_id, [e.evidence_id for e in experiment.evidence], ref)
    return {
        "run_id": run_id,
        "proposal_ready": True,
        "wait_seconds": 30 if run["scenario"] == "control-expiry" else 900,
    }


def register(event, context):
    control().wait(event["run_id"], event["token"])
    return {"registered": True}


def deliver_callback(run_id):
    c = control()
    item = c.db.get("approvals", run_id)
    if not item or item["status"] not in {"approved", "rejected"} or item["callback"] != "pending":
        return
    if now().timestamp() >= item["expires"]:
        return
    states = client("stepfunctions")
    try:
        states.send_task_success(
            taskToken=item["token"], output=encode({"run_id": run_id, "decision": item["status"]})
        )
    except (
        states.exceptions.TaskTimedOut,
        states.exceptions.InvalidToken,
        states.exceptions.TaskDoesNotExist,
    ):
        # Ambiguous delivered/expired callback: SFN catch or executor owns reconciliation.
        # Never change approval authority based only on a failed callback response.
        return
    try:
        c.db.commit([("approvals", run_id, item, item | {"callback": "delivered"})])
    except Conflict:
        pass  # Executor or timeout already advanced the same version.


def recover_callbacks(event, context):
    c = control()
    for run_id, item in c.db.scan("approvals", "p07-"):
        if (
            item["status"] in {"waiting", "approved", "rejected"}
            and now().timestamp() >= item["expires"]
        ):
            c.finish(run_id, "expired")
            continue
        if item["callback"] == "pending":
            deliver_callback(run_id)
    return {"recovery": "scanned"}


def execute(event, context):
    receipt = control().execute(event["run_id"], os.environ["APPROVER_ROLE"])
    return {"run_id": event["run_id"], "receipt_id": receipt["receipt_id"]}


def observe(event, context):
    """Independent synthetic probe after execution; it never trusts executor success output."""
    c, run_id = control(), event["run_id"]
    run = c.db.get("runs", "run#" + run_id)
    service = c.db.get("sandbox", "service#" + run_id)
    receipt = c.db.get("sandbox", "receipt#" + run_id)
    at = now()
    healthy = run["scenario"] != "control-unresolved"
    data = {
        "run_id": run_id,
        "synthetic": True,
        "source": "independent-health-probe-v1",
        "observed_at": at.isoformat(),
        "release": service["release"],
        "error_rate": 0.001 if healthy else 0.2,
        "latency_p95_ms": 120,
        "dependency_state": "healthy",
        "evidence_id": "verification-" + run_id,
    }
    # Retry uses the first immutable observation, not a new observation that could erase failure.
    key = f"runs/p07/{run_id}/verification.json"
    try:
        data = read_artifact(key)
    except client("s3").exceptions.NoSuchKey:
        artifact(key, data)
    verified = (
        receipt is not None
        and data["release"] == "release-41"
        and data["error_rate"] <= 0.01
        and data["latency_p95_ms"] <= 500
        and data["dependency_state"] == "healthy"
        and data["run_id"] == run_id
        and service["release"] == data["release"]
        and at - datetime.fromisoformat(data["observed_at"]) <= timedelta(minutes=5)
        and datetime.fromisoformat(receipt["receipt"]["audited_at"])
        < datetime.fromisoformat(data["observed_at"])
        <= at
    )
    return c.finish(
        run_id,
        "resolved" if verified else "unresolved",
        verification={"key": key, "sha256": content_hash(data)},
    )


def finish(event, context):
    return control().finish(event["run_id"], event.get("status", "failed"))
