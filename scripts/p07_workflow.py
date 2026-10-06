"""Signed CLI and bounded P07 acceptance harness. Temporary credentials stay in memory."""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config

from incident_demo.live.budget import CloudBudget
from incident_demo.live.contracts import LiveRequest
from incident_demo.workflow.repository import Repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "infra"))
from budget import LEDGER, reserve  # noqa: E402

CONFIG = Config(connect_timeout=5, read_timeout=160, retries={"total_max_attempts": 1})


class Operator:
    def __init__(self):
        self.sdk = boto3.Session(profile_name="incident-demo", region_name="us-east-2")
        if self.sdk.client("sts", config=CONFIG).get_caller_identity()["Account"] != "498084841421":
            raise ValueError("wrong account")
        self.outputs = json.loads((ROOT / "infra/cdk.out/workflow-outputs.json").read_text())[
            "incident-demo-workflow"
        ]
        self.sessions = {}

    def session(self, role):
        if role not in self.sessions:
            credentials = self.sdk.client("sts", config=CONFIG).assume_role(
                RoleArn=self.outputs[role.title() + "RoleOutput"],
                RoleSessionName="p07-signed-cli",
                DurationSeconds=3600,
            )["Credentials"]
            self.sessions[role] = boto3.Session(
                region_name="us-east-2",
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
            )
        return self.sessions[role]

    def api(self, role, method, path, body=None):
        url = self.outputs["ApiUrlOutput"] + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"content-type": "application/json"}
        if role:
            signed = AWSRequest(method=method, url=url, data=data, headers=headers)
            SigV4Auth(
                self.session(role).get_credentials().get_frozen_credentials(),
                "execute-api",
                "us-east-2",
            ).add_auth(signed)
            headers = dict(signed.headers)
        try:
            with urlopen(
                Request(url, data=data, headers=headers, method=method), timeout=20
            ) as reply:
                return reply.status, json.loads(reply.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def invoke(self, name, payload):
        reply = self.sdk.client("lambda", config=CONFIG).invoke(
            FunctionName=name, Payload=json.dumps(payload).encode()
        )
        with reply["Payload"] as stream:
            result = json.load(stream)
        if reply.get("FunctionError"):
            raise RuntimeError(json.dumps(result))
        return result

    def reserve(self, run_id, cloud=False):
        ledger = json.loads(LEDGER.read_text())
        if not any(r["batch_id"] == run_id for r in ledger["reservations"]):
            reserve(run_id, Decimal("0.75"))
        if cloud:
            request = LiveRequest.model_validate_json(
                json.dumps(
                    json.loads((ROOT / ".tools/p07-build/package.json").read_text())["live_request"]
                    | {"run_id": run_id}
                )
            )
            budget = CloudBudget(self.sdk, "incident-demo-live-budget")
            table = self.sdk.resource("dynamodb", config=CONFIG).Table("incident-demo-live-budget")
            if "Item" not in table.get_item(Key={"pk": "run#" + run_id}, ConsistentRead=True):
                budget.reserve(request)
                budget.release_lease(request)

    def start(self, scenario, key):
        role = "analyst" if scenario == "investigate" else "tester"
        run_id = (
            "p07-"
            + sha256((self.outputs[role.title() + "RoleOutput"] + ":" + key).encode()).hexdigest()[
                :40
            ]
        )
        if scenario == "investigate":
            self.reserve(run_id)
        return self.api(
            role,
            "POST",
            "/incidents" if role == "analyst" else "/control-tests",
            {"idempotency_key": key, "scenario": scenario},
        )

    def wait(self, run_id, states, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code, run = self.api("analyst", "GET", "/runs/" + run_id)
            if code == 200 and run["status"] in states:
                return run
            time.sleep(3)
        raise TimeoutError("workflow did not reach expected state")

    def decide(self, run, decision):
        return self.api(
            "approver",
            "POST",
            f"/runs/{run['run_id']}/decision",
            {
                "proposal_hash": run["proposal"]["proposal_hash"],
                "decision": decision,
                "reason": "Automated P07 control test; not independent human model review.",
                "facts_reviewed": True,
                "citations_reviewed": True,
            },
        )

    def snapshot(self, run_id):
        db = Repository(
            self.sdk.client("dynamodb", config=CONFIG),
            {n: self.outputs[n.title() + "TableOutput"] for n in ("runs", "approvals", "sandbox")},
        )
        run = db.get("runs", "run#" + run_id)
        approval = db.get("approvals", run_id)
        if approval:
            approval = {k: v for k, v in approval.items() if k != "token"}
        execution = (
            self.outputs["MachineArnOutput"].replace(":stateMachine:", ":execution:") + ":" + run_id
        )
        states = self.sdk.client("stepfunctions", config=CONFIG)
        history = []
        for page in states.get_paginator("get_execution_history").paginate(
            executionArn=execution, includeExecutionData=False
        ):
            # Allowlist avoids callback tokens even if service changes metadata behavior.
            history.extend(
                {
                    "id": e["id"],
                    "type": e["type"],
                    "timestamp": e["timestamp"].isoformat(),
                    "state": e.get("stateEnteredEventDetails", {}).get("name"),
                }
                for e in page["events"]
            )
        return {
            "run": run,
            "approval": approval,
            "service": db.get("sandbox", "service#" + run_id),
            "receipt": db.get("sandbox", "receipt#" + run_id),
            "execution_events": history,
        }


def smoke(op, folder):
    folder.mkdir(parents=True, exist_ok=False)
    op.reserve("p07-control-tests-v1", cloud=True)
    checks = []

    def check(name, condition):
        checks.append({"check": name, "passed": bool(condition)})
        (folder / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        if not condition:
            raise AssertionError(name)

    code, _ = op.api(None, "POST", "/incidents", {})
    check("unsigned intake denied", code == 403)
    time.sleep(2)
    code, _ = op.api("analyst", "POST", "/control-tests", {})
    check("analyst cannot create controlled proposal", code == 403)
    for scenario, decision, terminal in [
        ("control-recovery", "approved", "resolved"),
        ("control-unresolved", "approved", "unresolved"),
        ("control-recovery", "rejected", "rejected"),
        ("control-expiry", None, "expired"),
    ]:
        key = "accept-" + uuid4().hex
        time.sleep(2)
        code, submitted = op.start(scenario, key)
        check(f"{terminal}: intake", code == 202)
        rid = submitted["run_id"]
        (folder / (terminal + "-intake.json")).write_text(json.dumps(submitted, indent=2) + "\n")
        time.sleep(2)
        code, duplicate = op.start(scenario, key)
        check(f"{terminal}: intake replay stable", code == 202 and duplicate["run_id"] == rid)
        if scenario != "control-expiry":
            op.invoke("incident-demo-p07-dispatch", {})
        run = op.wait(rid, {"awaiting_approval", "failed"})
        check(f"{terminal}: approval wait", run["status"] == "awaiting_approval")
        if decision:
            time.sleep(2)
            code, _ = op.api("analyst", "POST", f"/runs/{rid}/decision", {})
            check(f"{terminal}: analyst decision denied", code == 403)
            time.sleep(2)
            code, review = op.api("approver", "GET", f"/runs/{rid}?review=true")
            check(
                f"{terminal}: immutable investigation review",
                code == 200 and review.get("investigation", {}).get("model_generated") is False,
            )
            time.sleep(2)
            edited = {
                "proposal_hash": "0" * 64,
                "decision": decision,
                "reason": "edited hash probe",
                "facts_reviewed": True,
                "citations_reviewed": True,
            }
            code, _ = op.api("approver", "POST", f"/runs/{rid}/decision", edited)
            check(f"{terminal}: edited hash denied", code == 409)
            time.sleep(2)
            code, _ = op.decide(run, decision)
            check(f"{terminal}: signed decision", code == 202)
        final = op.wait(rid, {terminal, "failed"})
        check(f"{terminal}: final status", final["status"] == terminal)
        snapshot = op.snapshot(rid)
        (folder / (terminal + ".json")).write_text(json.dumps(snapshot, indent=2) + "\n")
        check(
            f"{terminal}: token absent from exported evidence",
            "secret-token" not in json.dumps(snapshot) and '"token"' not in json.dumps(snapshot),
        )
        if decision == "approved":
            first = snapshot["receipt"]["receipt"]
            op.invoke("incident-demo-executor", {"run_id": rid})
            again = op.snapshot(rid)
            check(
                f"{terminal}: retry preserves receipt and revision",
                again["receipt"]["receipt"] == first and again["service"]["revision"] == 1,
            )
            time.sleep(2)
            code, _ = op.decide(run, decision)
            check(f"{terminal}: duplicate decision acknowledged", code == 202)
            time.sleep(2)
            code, _ = op.decide(run, "rejected")
            check(f"{terminal}: conflicting decision denied", code == 409)
            op.invoke("incident-demo-p07-starter", {"detail": {"run_id": rid}})
            trace = op.snapshot(rid)
            check(
                f"{terminal}: duplicate event cannot restart",
                sum(e["type"] == "ExecutionStarted" for e in trace["execution_events"]) == 1
                and trace["service"]["revision"] == 1,
            )
        else:
            check(
                f"{terminal}: no mutation",
                snapshot["receipt"] is None and snapshot["service"]["revision"] == 0,
            )
            if terminal == "expired":
                time.sleep(2)
                code, _ = op.decide(run, "approved")
                check("expired: late decision denied", code == 409)
        print(
            json.dumps({"scenario": scenario, "run_id": rid, "status": final["status"]}), flush=True
        )
    (folder / "completed.json").write_text(
        json.dumps({"at": datetime.now(UTC).isoformat(), "checks": len(checks)}) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["smoke", "start", "status", "review", "decide", "snapshot"]
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--proposal-hash")
    parser.add_argument("--decision", choices=["approved", "rejected"])
    parser.add_argument("--reason")
    parser.add_argument("--facts-reviewed", action="store_true")
    parser.add_argument("--citations-reviewed", action="store_true")
    parser.add_argument("--key", default="cli-" + uuid4().hex)
    parser.add_argument(
        "--scenario",
        default="investigate",
        choices=["investigate", "control-recovery", "control-unresolved", "control-expiry"],
    )
    args = parser.parse_args()
    op = Operator()
    if args.action == "smoke":
        if not args.output:
            parser.error("--output is required")
        smoke(op, args.output)
    elif args.action == "start":
        print(json.dumps(op.start(args.scenario, args.key)))
    elif args.action == "status":
        print(json.dumps(op.api("analyst", "GET", "/runs/" + args.run_id)))
    elif args.action == "review":
        print(json.dumps(op.api("approver", "GET", "/runs/" + args.run_id + "?review=true")))
    elif args.action == "decide":
        if not all(
            (
                args.run_id,
                args.proposal_hash,
                args.decision,
                args.reason,
                args.facts_reviewed,
                args.citations_reviewed,
            )
        ):
            parser.error(
                "decision requires run ID, proposal hash, decision, reason and both review flags"
            )
        print(
            json.dumps(
                op.api(
                    "approver",
                    "POST",
                    f"/runs/{args.run_id}/decision",
                    {
                        "proposal_hash": args.proposal_hash,
                        "decision": args.decision,
                        "reason": args.reason,
                        "facts_reviewed": True,
                        "citations_reviewed": True,
                    },
                )
            )
        )
    elif args.action == "snapshot":
        args.output.write_text(json.dumps(op.snapshot(args.run_id), indent=2) + "\n")


if __name__ == "__main__":
    main()
