import json

import aws_cdk as cdk
from aws_cdk.assertions import Template
from cdk_nag import AwsSolutionsChecks

from retrieval_stack import RetrievalStack
from settings import ROOT, load_config


def test_retrieval_is_frozen_private_and_region_scoped():
    app = cdk.App(context=json.loads((ROOT / "cdk.json").read_text())["context"])
    stack = RetrievalStack(app, load_config())
    template = Template.from_stack(stack)
    assert AwsSolutionsChecks(app).validate_scope(app).success
    template.has_resource_properties("AWS::S3Vectors::Index", {"Dimension": 1024})
    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "DataDeletionPolicy": "RETAIN",
            "VectorIngestionConfiguration": {"ChunkingConfiguration": {"ChunkingStrategy": "NONE"}},
        },
    )
    template.resource_count_is("AWS::Bedrock::GuardrailVersion", 1)
    resources = template.to_json()["Resources"]
    for resource in resources.values():
        if resource["Type"] != "AWS::IAM::Role":
            assert resource["DeletionPolicy"] == "Retain"
    roles = template.find_resources("AWS::IAM::Role")
    encoded = json.dumps(roles)
    assert "incident-demo-state" not in encoded and "lambda:" not in encoded
    assert "aws:SourceAccount" in encoded and "aws:SourceArn" in encoded
