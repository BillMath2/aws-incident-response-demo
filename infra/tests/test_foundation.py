import json

import aws_cdk as cdk
import pytest
from aws_cdk import aws_s3 as s3
from aws_cdk.assertions import Match, Template
from cdk_nag import AwsSolutionsChecks

from foundation import Foundation
from settings import ROOT, load_config


@pytest.fixture(scope="module")
def template():
    context = json.loads((ROOT / "cdk.json").read_text())["context"]
    return Template.from_stack(Foundation(cdk.App(context=context), load_config()))


def test_private_storage_and_evidence_retention(template):
    template.resource_count_is("AWS::S3::Bucket", 2)
    for bucket in template.find_resources("AWS::S3::Bucket").values():
        assert bucket["DeletionPolicy"] == "Retain"
        assert bucket["UpdateReplacePolicy"] == "Retain"
        assert all(bucket["Properties"]["PublicAccessBlockConfiguration"].values())
        assert bucket["Properties"]["BucketEncryption"]
        assert bucket["Properties"]["OwnershipControls"]["Rules"] == [
            {"ObjectOwnership": "BucketOwnerEnforced"}
        ]
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "VersioningConfiguration": {"Status": "Enabled"},
            "LoggingConfiguration": Match.any_value(),
        },
    )
    # Every bucket denies plain HTTP, including the access-log sink.
    for policy in template.find_resources("AWS::S3::BucketPolicy").values():
        assert any(
            s.get("Effect") == "Deny"
            and s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false"
            for s in policy["Properties"]["PolicyDocument"]["Statement"]
        )


def test_bounded_table_and_logs(template):
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "DeletionProtectionEnabled": True,
            "TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True},
            "OnDemandThroughput": {"MaxReadRequestUnits": 10, "MaxWriteRequestUnits": 10},
            "PointInTimeRecoverySpecification": {
                "PointInTimeRecoveryEnabled": True,
                "RecoveryPeriodInDays": 7,
            },
        },
    )
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 7})


def test_foundation_has_no_execution_or_public_endpoints(template):
    types = {r["Type"] for r in template.to_json()["Resources"].values()}
    assert types <= {
        "AWS::S3::Bucket",
        "AWS::S3::BucketPolicy",
        "AWS::DynamoDB::Table",
        "AWS::Logs::LogGroup",
    }


def test_security_scanner_detects_an_unprotected_bucket():
    app = cdk.App()
    stack = cdk.Stack(app, "Unsafe")
    s3.Bucket(stack, "UnsafeBucket")
    report = AwsSolutionsChecks(app).validate_scope(app)
    assert not report.success
    assert any(v.rule_name == "AwsSolutions-S10" for v in report.violations)


@pytest.mark.parametrize("field,value", [("region", "us-east-1"), ("account", "unknown")])
def test_wrong_target_rejected(tmp_path, field, value):
    config = load_config()
    config[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_config(path)


def test_unapproved_budget_rejected(tmp_path):
    config = load_config()
    config["budget"]["per_batch"] = 11
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_config(path)


def test_dependency_project_is_isolated():
    assert (ROOT / "uv.lock").exists()
    assert "aws-cdk-lib" not in (ROOT.parent / "pyproject.toml").read_text()
