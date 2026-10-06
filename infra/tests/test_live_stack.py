import json
from zipfile import ZipFile

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from cdk_nag import AwsSolutionsChecks

from live_stack import LiveStack
from settings import ROOT, load_config


@pytest.fixture(scope="module")
def live_template(tmp_path_factory):
    package = tmp_path_factory.mktemp("asset") / "test.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr("main.py", "# offline infrastructure test")
    app = cdk.App(context=json.loads((ROOT / "cdk.json").read_text())["context"])
    stack = LiveStack(app, load_config(), package)
    template = Template.from_stack(stack)
    assert AwsSolutionsChecks(app).validate_scope(app).success
    return template


def test_investigator_cannot_access_business_state_or_execute(live_template):
    policies = live_template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policies.values()))["Properties"]["PolicyDocument"]["Statement"]
    actions = []
    for statement in statements:
        listed = statement["Action"]
        actions.extend([listed] if isinstance(listed, str) else listed)
    assert not any(a.startswith(("iam:", "states:", "organizations:")) for a in actions)
    assert "lambda:InvokeFunction" in actions
    assert "bedrock:InvokeModel" in actions
    assert "incident-demo-state" not in json.dumps(policies)
    assert "incident-demo-executor" not in json.dumps(policies)
    live_template.resource_count_is("AWS::Lambda::Function", 3)


def test_runtime_and_logs_are_bounded(live_template):
    live_template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "ProtocolConfiguration": "HTTP",
            "LifecycleConfiguration": {"IdleRuntimeSessionTimeout": 60, "MaxLifetime": 180},
        },
    )
    for group in live_template.find_resources("AWS::Logs::LogGroup").values():
        assert group["Properties"]["RetentionInDays"] == 7
        assert "KmsKeyId" in group["Properties"]
    for role in live_template.find_resources("AWS::IAM::Role").values():
        assert not role["Properties"].get("ManagedPolicyArns")
