"""Read-only final evidence capture; exports no credentials or callback tokens."""

import json
from datetime import UTC, datetime
from pathlib import Path

from p07_workflow import CONFIG, Operator

from incident_demo.contracts.base import content_hash
from incident_demo.workflow.repository import Repository

ROOT = Path(__file__).resolve().parents[1]


def main():
    op = Operator()
    folder = ROOT / "docs/evidence/p07"
    s3 = op.sdk.client("s3", config=CONFIG)
    db = Repository(
        op.sdk.client("dynamodb", config=CONFIG),
        {n: op.outputs[n.title() + "TableOutput"] for n in ("runs", "approvals", "sandbox")},
    )
    dispatch, artifacts = {}, []
    traces = [folder / "live-investigation.json"] + [
        folder / "controls-2" / (status + ".json")
        for status in ("resolved", "unresolved", "rejected", "expired")
    ]
    for path in traces:
        trace = json.loads(path.read_text())
        run = trace["run"]
        dispatch[run["run_id"]] = db.get("runs", "dispatch#" + run["run_id"])
        for kind in ("artifact", "verification"):
            ref = run.get(kind)
            if not ref:
                continue
            response = s3.get_object(
                Bucket="incident-demo-artifacts-498084841421-us-east-2", Key=ref["key"]
            )
            with response["Body"] as stream:
                document = json.load(stream)
            if content_hash(document) != ref["sha256"]:
                raise AssertionError("stored artifact hash mismatch")
            target = folder / "artifacts" / (run["run_id"] + "-" + kind + ".json")
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(document, indent=2) + "\n")
            artifacts.append(ref | {"file": target.relative_to(ROOT).as_posix()})
    budget = op.sdk.resource("dynamodb", config=CONFIG).Table("incident-demo-live-budget")
    stack = op.sdk.client("cloudformation", config=CONFIG).describe_stacks(
        StackName="incident-demo-workflow"
    )["Stacks"][0]
    audit = []
    for page in (
        op.sdk.client("logs", config=CONFIG)
        .get_paginator("filter_log_events")
        .paginate(logGroupName="/incident-demo/p07/intake", filterPattern='"api_request"')
    ):
        audit.extend(page["events"])
        if len(audit) >= 5:
            break
    audit = audit[:5]
    if not audit:
        raise AssertionError("no private API audit records found")
    summary = {
        "at": datetime.now(UTC).isoformat(),
        "stack_status": stack["StackStatus"],
        "dispatch": dispatch,
        "artifacts": artifacts,
        "budget": {
            key: budget.get_item(Key={"pk": key}, ConsistentRead=True)["Item"]
            for key in ("global", "batch#p07-dev-01")
        },
        "private_api_audit_sample": [
            {"timestamp": event["timestamp"], "message": event["message"]} for event in audit
        ],
    }
    (folder / "final-state.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({"artifacts_verified": len(artifacts), "audit_records": len(audit)}))


if __name__ == "__main__":
    main()
