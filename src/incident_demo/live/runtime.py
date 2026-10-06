"""IAM-fronted HTTP runtime. No approval or action endpoints exist here."""

import json
import os
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

from incident_demo.contracts.base import canonical_json
from incident_demo.live.budget import CloudBudget, reservation_cents
from incident_demo.live.clients import sdk_config, session
from incident_demo.live.contracts import LiveRequest

BUSY = Lock()
MAX_REQUEST_BYTES = 16384
MAX_RESPONSE_BYTES = 196608


def read_audit(path):
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"event": "audit_record_interrupted"})
    return events


def run_bounded(command, seconds):
    process = subprocess.Popen(command)
    try:
        return process.wait(timeout=seconds) == 0, False
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        return False, True


def execute(request, sdk):
    budget = CloudBudget(sdk, os.environ["BUDGET_TABLE"])
    budget.reserve(request)
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="investigation-") as folder:
            folder = Path(folder)
            input_path, result_path, audit_path = [
                folder / f"{n}.json" for n in ("input", "result", "audit")
            ]
            input_path.write_text(request.model_dump_json(), encoding="utf-8")
            ok, timed_out = run_bounded(
                [
                    sys.executable,
                    "-m",
                    "incident_demo.live.worker",
                    str(input_path),
                    str(result_path),
                    str(audit_path),
                ],
                request.settings.limits.deadline_seconds,
            )
            audit = read_audit(audit_path)
            result = (
                json.loads(result_path.read_text())
                if ok and result_path.exists()
                else {
                    "run_id": request.run_id,
                    "mode": "aws_live",
                    "status": "incomplete" if timed_out else "failed",
                    "stop_reason": "hard_deadline_exhausted" if timed_out else "worker_failed",
                    "investigation": None,
                    "usage_known": False,
                }
            )
            envelope = {
                "schema_version": "p06-v1",
                "run_id": request.run_id,
                "mode": "aws_live",
                "synthetic_telemetry": True,
                "guardrail_policy": {
                    "id": os.environ["GUARDRAIL_ID"],
                    "version": os.environ["GUARDRAIL_VERSION"],
                },
                "retrieval": {
                    "knowledge_base_id": os.environ["KNOWLEDGE_BASE_ID"],
                    "corpus_version": "1.0.0",
                    "search_type": "SEMANTIC",
                },
                "reserved_usd": f"{reservation_cents(request) / 100:.2f}",
                "settings": request.settings.model_dump(mode="json"),
                "result": result,
                "audit": audit,
                "usage_complete": (
                    ok
                    and not timed_out
                    and all(
                        sum(e["event"] == name + "_started" for e in audit)
                        == sum(e["event"] == name + "_finished" for e in audit)
                        for name in ("model", "retrieval", "guardrail")
                    )
                    and not any(e["event"] == "audit_record_interrupted" for e in audit)
                ),
                "worker_latency_ms": int((time.monotonic() - started) * 1000),
            }
            encoded = canonical_json(envelope).encode()
            if len(encoded) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds bound")
            key = f"runs/p06/{request.run_id}.json"
            sdk.client("s3", config=sdk_config(10)).put_object(
                Bucket=os.environ["ARTIFACT_BUCKET"],
                Key=key,
                Body=encoded,
                ContentType="application/json",
                IfNoneMatch="*",
            )
            envelope["artifact_key"] = key
            print(
                canonical_json(
                    {
                        "event": "investigation_finished",
                        "run_id": request.run_id,
                        "status": result.get("status", "probe"),
                        "worker_latency_ms": envelope["worker_latency_ms"],
                        "artifact_key": key,
                    }
                ),
                flush=True,
            )
            return envelope
    finally:
        budget.release_lease(request)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Never log request bodies or authentication headers.

    def reply(self, status, value):
        encoded = canonical_json(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        self.reply(
            200 if self.path == "/ping" else 404,
            {"status": "HealthyBusy" if BUSY.locked() else "Healthy"},
        )

    def do_POST(self):
        if self.path != "/invocations":
            return self.reply(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                return self.reply(413, {"error": "payload_size"})
            request = LiveRequest.model_validate_json(self.rfile.read(length))
        except (ValueError, TypeError):
            return self.reply(400, {"error": "invalid_request"})
        if not BUSY.acquire(blocking=False):
            return self.reply(429, {"error": "busy"})
        try:
            result = execute(request, session())
            self.reply(200, result)
        except Exception as exc:
            # Error category only; raw AWS/provider errors can include untrusted content.
            print(
                canonical_json(
                    {
                        "event": "runtime_failure",
                        "run_id": request.run_id,
                        "category": type(exc).__name__,
                    }
                ),
                flush=True,
            )
            self.reply(503, {"run_id": request.run_id, "error": "runtime_failed_closed"})
        finally:
            BUSY.release()


def main():
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
