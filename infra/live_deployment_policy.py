"""Additional P05-only execution policy; the deployed P04 policy remains unchanged."""

import json

from deployment_policy import policy as foundation_policy
from settings import load_config


def policy(config):
    account, region = config["account"], config["region"]
    base = foundation_policy(config)["Statement"]
    statements = []

    def allow(sid, actions, resources, conditions=None):
        statement = {"Sid": sid, "Effect": "Allow", "Action": actions, "Resource": resources}
        if conditions:
            statement["Condition"] = conditions
        statements.append(statement)

    roles = [
        f"arn:aws:iam::{account}:role/{name}"
        for name in (
            "incident-demo-investigator",
            "incident-demo-diag-service-health",
            "incident-demo-diag-recent-changes",
            "incident-demo-diag-recent-logs",
        )
    ]
    allow(
        "ProjectRoles",
        [
            f"iam:{action}"
            for action in (
                "CreateRole",
                "DeleteRole",
                "GetRole",
                "UpdateAssumeRolePolicy",
                "TagRole",
                "UntagRole",
                "PutRolePolicy",
                "GetRolePolicy",
                "DeleteRolePolicy",
                "ListRolePolicies",
                "ListAttachedRolePolicies",
            )
        ],
        roles,
    )
    allow(
        "PassProjectRoles",
        ["iam:PassRole"],
        roles,
        {
            "StringEquals": {
                "iam:PassedToService": ["lambda.amazonaws.com", "bedrock-agentcore.amazonaws.com"]
            }
        },
    )
    allow(
        "RuntimeIdentityServiceRole",
        ["iam:CreateServiceLinkedRole"],
        [
            f"arn:aws:iam::{account}:role/aws-service-role/"
            "runtime-identity.bedrock-agentcore.amazonaws.com/"
            "AWSServiceRoleForBedrockAgentCoreRuntimeIdentity"
        ],
        {
            "StringEquals": {
                "iam:AWSServiceName": "runtime-identity.bedrock-agentcore.amazonaws.com"
            }
        },
    )
    allow(
        "DiagnosticFunctions",
        [
            f"lambda:{action}"
            for action in (
                "CreateFunction",
                "DeleteFunction",
                "GetFunction",
                "GetFunctionConfiguration",
                "UpdateFunctionCode",
                "UpdateFunctionConfiguration",
                "GetFunctionConcurrency",
                "TagResource",
                "UntagResource",
                "ListTags",
                "GetRuntimeManagementConfig",
                "PutRuntimeManagementConfig",
            )
        ],
        [f"arn:aws:lambda:{region}:{account}:function:incident-demo-diag-*"],
    )
    allow(
        "InvestigatorRuntime",
        [
            f"bedrock-agentcore:{action}"
            for action in (
                "GetAgentRuntime",
                "UpdateAgentRuntime",
                "DeleteAgentRuntime",
                "CreateAgentRuntimeEndpoint",
                "GetAgentRuntimeEndpoint",
                "UpdateAgentRuntimeEndpoint",
                "DeleteAgentRuntimeEndpoint",
                "TagResource",
                "UntagResource",
                "ListTagsForResource",
            )
        ],
        [
            f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/incident_demo_investigator*",
        ],
    )
    allow(
        "CreateTaggedRuntime",
        [
            "bedrock-agentcore:CreateAgentRuntime",
            "bedrock-agentcore:CreateAgentRuntimeEndpoint",
            "bedrock-agentcore:CreateWorkloadIdentity",
        ],
        "*",
        {
            "StringEquals": {
                "aws:RequestTag/Project": "incident-demo",
                "aws:RequestedRegion": region,
            }
        },
    )
    allow(
        "TagRuntimeCreation",
        ["bedrock-agentcore:TagResource"],
        [
            f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/*",
            f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
            f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/"
            "workload-identity/*",
        ],
        {"StringEquals": {"aws:RequestTag/Project": "incident-demo"}},
    )
    allow(
        "RuntimeWorkloadIdentity",
        ["bedrock-agentcore:CreateWorkloadIdentity", "bedrock-agentcore:DeleteWorkloadIdentity"],
        [
            f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
            f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/"
            "workload-identity/incident_demo_investigator*",
        ],
    )
    allow(
        "BudgetTable",
        [
            f"dynamodb:{action}"
            for action in (
                "CreateTable",
                "UpdateTable",
                "DeleteTable",
                "DescribeTable",
                "TagResource",
                "UntagResource",
                "ListTagsOfResource",
                "UpdateContinuousBackups",
                "DescribeContinuousBackups",
                "DescribeContributorInsights",
                "GetResourcePolicy",
            )
        ],
        [f"arn:aws:dynamodb:{region}:{account}:table/incident-demo-live-budget"],
    )
    groups = [
        f"arn:aws:logs:{region}:{account}:log-group:{name}"
        for name in (
            "/aws/lambda/incident-demo-diag-*",
            "/aws/bedrock-agentcore/runtimes/incident_demo_investigator*",
        )
    ]
    allow(
        "ProjectLogs",
        base[3]["Action"] + ["logs:AssociateKmsKey", "logs:DisassociateKmsKey"],
        groups,
    )
    allow("RegionalLogDiscovery", base[4]["Action"], "*", base[4]["Condition"])
    allow(
        "CreateTaggedLogsKey",
        ["kms:CreateKey"],
        "*",
        {
            "StringEquals": {
                "aws:RequestTag/Project": "incident-demo",
                "aws:RequestedRegion": region,
            }
        },
    )
    allow(
        "ManageTaggedLogsKey",
        [
            f"kms:{action}"
            for action in (
                "DescribeKey",
                "GetKeyPolicy",
                "PutKeyPolicy",
                "ListResourceTags",
                "TagResource",
                "UntagResource",
                "EnableKeyRotation",
                "GetKeyRotationStatus",
            )
        ],
        [f"arn:aws:kms:{region}:{account}:key/*"],
        {"StringEquals": {"aws:ResourceTag/Project": "incident-demo"}},
    )
    bucket = f"incident-demo-trail-{account}-{region}"
    bucket_actions = [
        a
        for a in base[1]["Action"]
        if a
        not in {
            "s3:PutBucketAcl",
            "s3:PutBucketObjectLockConfiguration",
            "s3:GetBucketVersioning",
            "s3:PutBucketVersioning",
            "s3:GetBucketLogging",
            "s3:PutBucketLogging",
        }
    ]
    allow("TrailBucket", bucket_actions, [f"arn:aws:s3:::{bucket}"])
    allow(
        "CodeAssets",
        ["s3:GetObject", "s3:GetObjectVersion"],
        [f"arn:aws:s3:::cdk-incdemo-assets-{account}-{region}/*"],
    )
    allow(
        "ProjectTrail",
        [
            f"cloudtrail:{action}"
            for action in (
                "CreateTrail",
                "UpdateTrail",
                "DeleteTrail",
                "StartLogging",
                "StopLogging",
                "GetTrail",
                "GetTrailStatus",
                "PutEventSelectors",
                "GetEventSelectors",
                "AddTags",
                "RemoveTags",
                "ListTags",
            )
        ],
        [f"arn:aws:cloudtrail:{region}:{account}:trail/incident-demo-p05"],
    )
    # Keep descriptive labels in the authoring source, but omit optional Sids to
    # stay below IAM's 6,144-character managed-policy limit without widening scope.
    return {
        "Version": "2012-10-17",
        "Statement": [{k: v for k, v in s.items() if k != "Sid"} for s in statements],
    }


def monitoring_policy(config):
    account, region = config["account"], config["region"]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:PutMetricFilter",
                    "logs:DeleteMetricFilter",
                    "logs:DescribeMetricFilters",
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/"
                    "runtimes/incident_demo_investigator*"
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:PutMetricAlarm",
                    "cloudwatch:DeleteAlarms",
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:TagResource",
                    "cloudwatch:UntagResource",
                    "cloudwatch:ListTagsForResource",
                ],
                "Resource": [f"arn:aws:cloudwatch:{region}:{account}:alarm:incident-demo-p05-*"],
            },
        ],
    }


if __name__ == "__main__":
    print(json.dumps(policy(load_config()), indent=2))
