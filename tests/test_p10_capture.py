"""Evidence export must preserve reviewable data without leaking callback authority."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "p10_capture", Path(__file__).resolve().parents[1] / "scripts/p10_capture.py"
)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def test_sanitize_removes_nested_authority_without_changing_input():
    record = {
        "document": {"token": "callback-secret", "reason": "Reviewed", "proposal_hash": "abc"},
        "items": [{"TaskToken": "other-secret", "SessionToken": "aws-secret", "status": "closed"}],
    }
    cleaned = capture.sanitize(record)
    assert cleaned == {
        "document": {"reason": "Reviewed", "proposal_hash": "abc"},
        "items": [{"status": "closed"}],
    }
    assert record["document"]["token"] == "callback-secret"


def test_export_does_not_overwrite_retained_evidence(tmp_path):
    path = tmp_path / "evidence.json"
    capture.write_json(path, {"status": "unresolved"})
    with pytest.raises(FileExistsError):
        capture.write_json(path, {"status": "resolved"})
    assert json.loads(path.read_text()) == {"status": "unresolved"}


def test_bootstrap_yaml_retains_intrinsic_structure_without_execution():
    template = yaml.load(
        "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n    DeletionPolicy: Retain\n"
        "    Properties:\n      BucketName: !Sub demo-${AWS::AccountId}\n"
        "      Tags: !If [UseTags, {Key: Project, Value: demo}, !Ref AWS::NoValue]\n",
        Loader=capture.TemplateLoader,
    )
    bucket = template["Resources"]["Bucket"]
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["Properties"]["BucketName"] == {"Fn::Sub": "demo-${AWS::AccountId}"}
    assert bucket["Properties"]["Tags"]["Fn::If"][-1] == {"Ref": "AWS::NoValue"}
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("!!python/object/apply:os.system ['echo unsafe']", Loader=capture.TemplateLoader)
