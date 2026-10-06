"""Read back P07 controls and exercise actual denied calls under temporary human roles."""

import base64
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from botocore.exceptions import ClientError
from p07_workflow import CONFIG, Operator

ROOT = Path(__file__).resolve().parents[1]


def main():
    op = Operator()
    checks, observations = [], {}

    def check(name, passed):
        checks.append({"check": name, "passed": bool(passed)})

    cf = op.sdk.client("cloudformation", config=CONFIG)
    stack = cf.describe_stacks(StackName="incident-demo-workflow")["Stacks"][0]
    check("stack complete", stack["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"})
    check("termination protection", stack["EnableTerminationProtection"])
    api = op.sdk.client("apigatewayv2", config=CONFIG)
    api_id = op.outputs["ApiUrlOutput"].split("//")[1].split(".")[0]
    routes = api.get_routes(ApiId=api_id)["Items"]
    check(
        "all four routes use IAM",
        len(routes) == 4 and all(r["AuthorizationType"] == "AWS_IAM" for r in routes),
    )
    stage = api.get_stage(ApiId=api_id, StageName="$default")
    check(
        "API throttled with detailed metrics",
        stage["DefaultRouteSettings"]["ThrottlingRateLimit"] == 1
        and stage["DefaultRouteSettings"]["DetailedMetricsEnabled"],
    )
    observations["gateway_access_logs"] = (
        "disabled; API integration Lambdas emit private request audit"
    )
    states = op.sdk.client("stepfunctions", config=CONFIG)
    machine = states.describe_state_machine(stateMachineArn=op.outputs["MachineArnOutput"])
    check("Standard workflow", machine["type"] == "STANDARD")
    check(
        "no execution data in logs",
        machine["loggingConfiguration"]["includeExecutionData"] is False,
    )
    definition = json.loads(machine["definition"])
    check("bounded workflow", definition["TimeoutSeconds"] == 1200)
    observations["definition"] = definition
    bus_client = op.sdk.client("eventbridgev2", config=CONFIG)
    bus = bus_client.describe_event_bus(EventBusArn=op.outputs["BusArnOutput"])
    subscriber = bus_client.describe_subscriber(SubscriberArn=op.outputs["SubscriberArnOutput"])
    check("bus active", bus["State"] == "ACTIVE")
    check(
        "subscriber active with bounded retry and DLQ",
        subscriber["State"] == "RUNNING"
        and subscriber["RetryPolicy"]["MaxRetryAttempts"] == 1
        and bool(subscriber["OnFailureConfiguration"]),
    )
    observations["bus"] = {k: v for k, v in bus.items() if k != "ResponseMetadata"}
    observations["subscriber"] = {k: v for k, v in subscriber.items() if k != "ResponseMetadata"}
    db = op.sdk.client("dynamodb", config=CONFIG)
    for name in ("runs", "approvals", "sandbox"):
        table_name = op.outputs[name.title() + "TableOutput"]
        table = db.describe_table(TableName=table_name)["Table"]
        check(
            name + " encrypted/deletion protected",
            table["SSEDescription"]["Status"] == "ENABLED" and table["DeletionProtectionEnabled"],
        )
        backup = db.describe_continuous_backups(TableName=table_name)[
            "ContinuousBackupsDescription"
        ]
        check(
            name + " PITR enabled",
            backup["PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"] == "ENABLED",
        )
    # Invalid tokens are rejected before IAM evaluation. Use a real controlled wait;
    # the administrator reads its token only into memory, never into evidence or logs.
    code, intake = op.start("control-recovery", "callback-denial-" + uuid4().hex)
    if code != 202:
        raise AssertionError("callback probe intake failed")
    op.invoke("incident-demo-p07-dispatch", {})
    callback_run = op.wait(intake["run_id"], {"awaiting_approval", "failed"})
    if callback_run["status"] != "awaiting_approval":
        raise AssertionError("callback probe did not reach wait")
    item = db.get_item(
        TableName=op.outputs["ApprovalsTableOutput"],
        Key={"pk": {"S": intake["run_id"]}},
        ConsistentRead=True,
    )["Item"]
    task_token = json.loads(item["document"]["S"])["token"]
    observations["callback_probe_run_id"] = intake["run_id"]
    observations["denial_errors"] = {}
    for role in ("analyst", "approver", "tester"):
        sdk = op.session(role)
        attempts = {
            "executor invoke": lambda sdk=sdk: sdk.client("lambda", config=CONFIG).invoke(
                FunctionName="incident-demo-executor", InvocationType="DryRun"
            ),
            "callback": lambda sdk=sdk, token=task_token: sdk.client(
                "stepfunctions", config=CONFIG
            ).send_task_success(taskToken=token, output="{}"),
            "approval read": lambda sdk=sdk: sdk.client("dynamodb", config=CONFIG).get_item(
                TableName="incident-demo-p07-approvals",
                Key={"pk": {"S": "nonexistent-denial-probe"}},
            ),
            "workflow history": lambda sdk=sdk: sdk.client(
                "stepfunctions", config=CONFIG
            ).list_executions(stateMachineArn=op.outputs["MachineArnOutput"], maxResults=1),
        }
        for action, call in attempts.items():
            try:
                call()
                denied = False
            except ClientError as exc:
                denied = exc.response["Error"]["Code"] in {"AccessDeniedException", "AccessDenied"}
                observations["denial_errors"][role + ": " + action] = exc.response["Error"]["Code"]
            check(role + " denied " + action, denied)
    del task_token
    time.sleep(2)
    code, _ = op.decide(callback_run, "rejected")
    check("callback probe closed through signed rejection", code == 202)
    final = op.wait(intake["run_id"], {"rejected", "failed"})
    check("callback probe performed no action", final["status"] == "rejected")
    observations["callback_probe"] = op.snapshot(intake["run_id"])
    functions = op.sdk.client("lambda", config=CONFIG)
    names = [
        "intake",
        "decision",
        "read",
        "dispatch",
        "starter",
        "bridge",
        "register",
        "callbacks",
        "observe",
        "finish",
    ]
    configurations = [
        functions.get_function_configuration(FunctionName="incident-demo-p07-" + n) for n in names
    ]
    configurations.append(
        functions.get_function_configuration(FunctionName="incident-demo-executor")
    )
    check("eleven separate Lambda roles", len({c["Role"] for c in configurations}) == 11)
    check("one tested package", len({c["CodeSha256"] for c in configurations}) == 1)
    manifest = json.loads((ROOT / ".tools/p07-build/package.json").read_text())
    expected_hash = base64.b64encode(bytes.fromhex(manifest["sha256"])).decode()
    check(
        "deployed package matches local build",
        all(c["CodeSha256"] == expected_hash for c in configurations),
    )
    check("bounded Lambda timeouts", all(c["Timeout"] <= 150 for c in configurations))
    observations["functions"] = [
        {k: c[k] for k in ("FunctionName", "Role", "CodeSha256", "Timeout", "Runtime")}
        for c in configurations
    ]
    table = op.sdk.resource("dynamodb", config=CONFIG).Table("incident-demo-live-budget")
    observations["budget"] = {
        key: table.get_item(Key={"pk": key}, ConsistentRead=True)["Item"]
        for key in ("global", "batch#p07-dev-01")
    }
    observations["at"] = datetime.now(UTC).isoformat()
    folder = ROOT / "docs/evidence/p07"
    (folder / "readback.json").write_text(json.dumps(observations, indent=2, default=str) + "\n")
    (folder / "readback-checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(json.dumps({"passed": sum(c["passed"] for c in checks), "total": len(checks)}))
    if not all(c["passed"] for c in checks):
        raise AssertionError("readback failed")


if __name__ == "__main__":
    main()
