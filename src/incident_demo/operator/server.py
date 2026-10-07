"""Loopback-only bridge with strict routes, origin checks and an in-memory page token."""

import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from incident_demo.contracts.base import content_hash
from incident_demo.workflow.durable import Decision, Intake

STATIC = Path(__file__).parent / "static"
RUN_ID = r"p07-[a-f0-9]{40}"
PUBLIC_FIELDS = {
    "run_id",
    "scenario",
    "status",
    "proposal",
    "artifact",
    "verification",
    "history",
    "approval_id",
    "investigation",
}


class OperatorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, backend, examples):
        self.backend, self.examples = backend, examples
        self.token = secrets.token_urlsafe(32)
        self.operation_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(25)

    def log_message(self, *args):
        # No body, credentials, tokens or query strings in request logs.
        pass

    def send(self, status, value, content_type="application/json"):
        data = json.dumps(value).encode() if content_type == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, api=False):
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            return False
        return not api or secrets.compare_digest(
            self.headers.get("X-Operator-Token", ""), self.server.token
        )

    def do_GET(self):
        api = self.path.startswith("/api/")
        if not self.authorized(api):
            return self.send(403, {"error": "forbidden"})
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if self.path in assets:
            name, kind = assets[self.path]
            data = (
                (STATIC / name).read_bytes().replace(b"__PAGE_TOKEN__", self.server.token.encode())
            )
            return self.send(200, data, kind)
        if self.path == "/api/config":
            return self.send(
                200,
                {
                    "mode": "cloud" if self.server.backend else "replay",
                    "region": "us-east-2",
                    "examples": [
                        {"id": key, "label": item["label"]}
                        for key, item in self.server.examples.items()
                    ],
                },
            )
        match = re.fullmatch(r"/api/examples/([a-z0-9-]+)", self.path)
        if match and match[1] in self.server.examples:
            return self.send(200, self.server.examples[match[1]])
        match = re.fullmatch(rf"/api/runs/({RUN_ID})", self.path)
        if match:
            return self.cloud("review", match[1])
        self.send(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authorized(True):
            return self.send(403, {"error": "forbidden"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < length <= 8192
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Type") != "application/json"
            ):
                return self.send(400, {"error": "invalid_request"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected object")
            if self.path == "/api/incidents":
                intake = Intake.model_validate(body | {"scenario": "investigate"})
                if set(body) != {"idempotency_key"}:
                    raise ValueError("Unexpected fields")
                return self.cloud("start", intake.idempotency_key)
            match = re.fullmatch(rf"/api/runs/({RUN_ID})/decision", self.path)
            if match:
                decision = Decision.model_validate(body)
                if not decision.reason.strip():
                    raise ValueError("Reason required")
                return self.cloud("decide", match[1], decision.model_dump(mode="json"))
        except (ValueError, TypeError):
            return self.send(400, {"error": "invalid_request"})
        self.send(404, {"error": "not_found"})

    def cloud(self, operation, *args):
        if not self.server.backend:
            return self.send(409, {"error": "replay_only"})
        try:
            # Serialize SDK sessions, reservations and mutations across browser tabs.
            with self.server.operation_lock:
                code, result = getattr(self.server.backend, operation)(*args)
            if code < 300 and operation in {"review", "start"}:
                result = {k: v for k, v in result.items() if k in PUBLIC_FIELDS}
            return self.send(code, result)
        except Exception:
            # The user may refresh status/retry the SAME intake key after an unknown outcome.
            # Never retry a mutation automatically or expose SDK exceptions to the browser.
            return self.send(502, {"error": "cloud_unavailable_or_outcome_unknown"})


def load_examples(root):
    examples = {}
    for outcome in ("resolved", "unresolved", "rejected", "expired"):
        path = root / "docs/evidence/p07/controls-2" / (outcome + ".json")
        if path.exists():
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            records = {}
            for field, suffix in (("artifact", "artifact"), ("verification", "verification")):
                reference = snapshot["run"].get(field)
                if reference:
                    record_path = (
                        root
                        / "docs/evidence/p07/artifacts"
                        / (snapshot["run"]["run_id"] + "-" + suffix + ".json")
                    )
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    if content_hash(record) != reference["sha256"]:
                        raise ValueError("Retained control artifact hash mismatch")
                    records[field] = record
            examples[outcome] = {
                "label": f"Recorded control: {outcome}",
                "provenance": "Recorded P07 synthetic control; no model generated this proposal.",
                "run": {k: v for k, v in snapshot["run"].items() if k in PUBLIC_FIELDS}
                | {"investigation": records.get("artifact")},
                "receipt": snapshot.get("receipt"),
                "verification_record": records.get("verification"),
            }
    for number in range(1, 9):
        case = f"case-{number:03d}"
        path = root / f"docs/evidence/p08/repair-v5/results/repair-{case}-v2-lite-r1.json"
        if path.exists():
            trial = json.loads(path.read_text(encoding="utf-8"))
            examples[case] = {
                "label": f"Recorded model investigation: {case}",
                "provenance": "Recorded P08 / Nova Lite / V2 / runtime 13. Known reasoning "
                "limitations accepted for the demo. No action was executed.",
                "run": {
                    "run_id": trial["run_id"],
                    "status": "recorded_investigation",
                    "investigation": trial["response"],
                },
            }
    return examples
