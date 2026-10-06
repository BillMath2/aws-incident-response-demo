import json
from zipfile import ZipFile

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from cdk_nag import AwsSolutionsChecks

from settings import ROOT, load_config
from workflow_stack import WorkflowStack


@pytest.fixture(scope="module")
def workflow(tmp_path_factory):
    package = tmp_path_factory.mktemp("workflow") / "code.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr("main.py", "# infrastructure test")
    app = cdk.App(context=json.loads((ROOT / "cdk.json").read_text())["context"])
    live = {
        "RuntimeArnOutput": "arn:aws:bedrock-agentcore:us-east-2:498084841421:runtime/test",
        "EndpointArnOutput": (
            "arn:aws:bedrock-agentcore:us-east-2:498084841421:runtime/test/runtime-endpoint/smoke"
        ),
    }
    stack = WorkflowStack(app, load_config(), package, live, {"batch_id": "p07-dev-01"})
    template = Template.from_stack(stack).to_json()
    assert AwsSolutionsChecks(app).validate_scope(app).success
    return template["Resources"]


def test_only_signed_routes_and_separate_user_roles(workflow):
    routes = [v["Properties"] for v in workflow.values() if v["Type"] == "AWS::ApiGatewayV2::Route"]
    assert len(routes) == 4 and all(r["AuthorizationType"] == "AWS_IAM" for r in routes)
    policies = {
        k: json.dumps(v["Properties"]["PolicyDocument"])
        for k, v in workflow.items()
        if v["Type"] == "AWS::IAM::Policy"
    }
    analyst = next(v for k, v in policies.items() if k.startswith("analystUserRole"))
    approver = next(v for k, v in policies.items() if k.startswith("approverUserRole"))
    assert "POST/incidents" in analyst and "POST/runs/*/decision" not in analyst
    assert "POST/runs/*/decision" in approver and "POST/incidents" not in approver
    assert all("states:SendTaskSuccess" not in p for p in (analyst, approver))
    executor = next(v for k, v in policies.items() if k.startswith("executorRole"))
    assert '"Effect": "Deny"' in executor and "states:SendTaskSuccess" not in executor
    bridge = next(v for k, v in policies.items() if k.startswith("bridgeRole"))
    assert "bedrock-agentcore:InvokeAgentRuntime" in bridge
    assert "lambda:InvokeFunction" not in bridge and "states:SendTaskSuccess" not in bridge


def test_wait_tokens_stay_server_side_and_tasks_are_bounded(workflow):
    machine = workflow["Machine"]["Properties"]
    assert machine["StateMachineType"] == "STANDARD"
    assert machine["LoggingConfiguration"]["IncludeExecutionData"] is False
    definition = machine["Definition"]
    assert definition["TimeoutSeconds"] == 1200
    states = definition["States"]
    assert states["Approval"]["Resource"].endswith(".waitForTaskToken")
    assert states["Approval"]["Parameters"]["Payload"]["token.$"] == "$$.Task.Token"
    assert "Retry" not in states["Approval"]
    assert states["Execute"]["Next"] == "Observe"
    for task in states.values():
        if task["Type"] == "Task":
            assert "TimeoutSeconds" in task or "TimeoutSecondsPath" in task
            assert all(r["MaxAttempts"] <= 1 for r in task.get("Retry", []))


def test_durable_storage_dispatch_and_dead_letters(workflow):
    tables = [v for v in workflow.values() if v["Type"] == "AWS::DynamoDB::Table"]
    assert len(tables) == 3
    assert all(t["DeletionPolicy"] == "Retain" for t in tables)
    assert all("TimeToLiveSpecification" not in t["Properties"] for t in tables)
    assert workflow["Bus"]["Type"] == "AWS::EventsV2::EventBus"
    subscriber = workflow["Subscriber"]["Properties"]
    assert subscriber["RetryPolicy"]["MaxRetryAttempts"] == 1
    assert "OnFailureConfiguration" in subscriber
    schedules = [v for v in workflow.values() if v["Type"] == "AWS::Events::Rule"]
    assert len(schedules) == 2
    assert all(r["Properties"]["ScheduleExpression"] == "rate(1 minute)" for r in schedules)
