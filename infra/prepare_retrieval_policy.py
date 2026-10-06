"""Install only the P06 CFN permissions, separately from the frozen P04/P05 policies."""

from manage import verify_identity
from prepare_live_policy import install
from settings import load_config


def policy(config):
    account, region = config["account"], config["region"]
    role = f"arn:aws:iam::{account}:role/incident-demo-knowledge"
    vector = f"arn:aws:s3vectors:{region}:{account}:bucket/incident-demo-vectors-{account}-{region}"
    bedrock = f"arn:aws:bedrock:{region}:{account}:"
    statements = []

    def allow(actions, resources, conditions=None):
        item = dict(Effect="Allow", Action=actions, Resource=resources)
        if conditions:
            item["Condition"] = conditions
        statements.append(item)

    allow(
        [
            "iam:" + a
            for a in (
                "CreateRole",
                "GetRole",
                "DeleteRole",
                "TagRole",
                "UntagRole",
                "PutRolePolicy",
                "GetRolePolicy",
                "DeleteRolePolicy",
                "ListRolePolicies",
                "ListAttachedRolePolicies",
                "UpdateAssumeRolePolicy",
            )
        ],
        [role],
    )
    allow(
        ["iam:PassRole"], [role], {"StringEquals": {"iam:PassedToService": "bedrock.amazonaws.com"}}
    )
    allow(
        [
            "s3vectors:" + a
            for a in (
                "CreateVectorBucket",
                "GetVectorBucket",
                "DeleteVectorBucket",
                "TagResource",
                "UntagResource",
                "ListTagsForResource",
                "CreateIndex",
                "GetIndex",
                "DeleteIndex",
            )
        ],
        [vector, vector + "/index/runbooks-v1"],
    )
    allow(
        ["bedrock:CreateKnowledgeBase", "bedrock:CreateGuardrail"],
        ["*"],
        {
            "StringEquals": {
                "aws:RequestedRegion": region,
                "aws:RequestTag/Project": "incident-demo",
            }
        },
    )
    allow(
        [
            "bedrock:" + a
            for a in (
                "GetKnowledgeBase",
                "UpdateKnowledgeBase",
                "DeleteKnowledgeBase",
                "CreateDataSource",
                "GetDataSource",
                "UpdateDataSource",
                "DeleteDataSource",
            )
        ],
        [bedrock + "knowledge-base/*"],
        {"StringEquals": {"aws:ResourceTag/Project": "incident-demo"}},
    )
    allow(
        [
            "bedrock:" + a
            for a in (
                "GetGuardrail",
                "UpdateGuardrail",
                "DeleteGuardrail",
                "CreateGuardrailVersion",
            )
        ],
        [bedrock + "guardrail/*"],
        {"StringEquals": {"aws:ResourceTag/Project": "incident-demo"}},
    )
    allow(
        ["bedrock:TagResource", "bedrock:UntagResource", "bedrock:ListTagsForResource"],
        [bedrock + "knowledge-base/*", bedrock + "guardrail/*"],
    )
    return {"Version": "2012-10-17", "Statement": statements}


def main():
    config = load_config()
    verify_identity(config)
    install(
        config, policy(config), "incident-demo-p06-cfn-execution", "cfn-execution-policy", "p06"
    )


if __name__ == "__main__":
    main()
