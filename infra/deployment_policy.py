"""Generate the P04-only CloudFormation execution policy for the configured target."""

import json

from settings import load_config


def policy(config: dict) -> dict:
    account, region = config["account"], config["region"]
    buckets = [
        f"arn:aws:s3:::incident-demo-{purpose}-{account}-{region}"
        for purpose in ("artifacts", "access-logs")
    ]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadBootstrapVersion",
                "Effect": "Allow",
                "Action": "ssm:GetParameters",
                "Resource": (
                    f"arn:aws:ssm:{region}:{account}:parameter/cdk-bootstrap/"
                    f"{config['bootstrap_qualifier']}/version"
                ),
            },
            {
                "Sid": "FoundationBuckets",
                "Effect": "Allow",
                "Action": [
                    f"s3:{action}"
                    for action in (
                        "CreateBucket",
                        "DeleteBucket",
                        "ListBucket",
                        "GetBucketAcl",
                        "PutBucketAcl",
                        "PutBucketObjectLockConfiguration",
                        "GetBucketLocation",
                        "GetBucketTagging",
                        "PutBucketTagging",
                        "GetBucketPolicy",
                        "PutBucketPolicy",
                        "DeleteBucketPolicy",
                        "GetBucketPublicAccessBlock",
                        "PutBucketPublicAccessBlock",
                        "GetEncryptionConfiguration",
                        "PutEncryptionConfiguration",
                        "GetLifecycleConfiguration",
                        "PutLifecycleConfiguration",
                        "GetBucketVersioning",
                        "PutBucketVersioning",
                        "GetBucketOwnershipControls",
                        "PutBucketOwnershipControls",
                        "GetBucketLogging",
                        "PutBucketLogging",
                    )
                ],
                "Resource": buckets,
            },
            {
                "Sid": "FoundationTable",
                "Effect": "Allow",
                "Action": [
                    f"dynamodb:{action}"
                    for action in (
                        "CreateTable",
                        "UpdateTable",
                        "DeleteTable",
                        "DescribeTable",
                        "TagResource",
                        "UntagResource",
                        "ListTagsOfResource",
                        "UpdateTimeToLive",
                        "DescribeTimeToLive",
                        "UpdateContinuousBackups",
                        "DescribeContinuousBackups",
                        "DescribeContributorInsights",
                        "GetResourcePolicy",
                        "PutResourcePolicy",
                        # Dependent actions listed by AWS's Create/UpdateTable reference.
                        "AssociateTableReplica",
                        "CreateTableReplica",
                        "BatchWriteItem",
                        "DeleteItem",
                        "GetItem",
                        "PutItem",
                        "Query",
                        "Scan",
                        "UpdateItem",
                        "CreateGlobalTableWitness",
                        "DeleteGlobalTableWitness",
                        "ReplicateSettings",
                        "WriteDataForReplication",
                    )
                ],
                "Resource": f"arn:aws:dynamodb:{region}:{account}:table/incident-demo-state",
                "Condition": {"StringEquals": {"aws:RequestedRegion": region}},
            },
            {
                "Sid": "FoundationLogGroup",
                "Effect": "Allow",
                "Action": [
                    f"logs:{action}"
                    for action in (
                        "CreateLogGroup",
                        "DeleteLogGroup",
                        "PutRetentionPolicy",
                        "DeleteRetentionPolicy",
                        "TagLogGroup",
                        "UntagLogGroup",
                        "TagResource",
                        "UntagResource",
                        "ListTagsLogGroup",
                        "ListTagsForResource",
                        "GetDataProtectionPolicy",
                    )
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account}:log-group:/incident-demo/foundation",
                    f"arn:aws:logs:{region}:{account}:log-group:/incident-demo/foundation:*",
                ],
            },
            {
                "Sid": "RegionalLogDiscovery",
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogGroups",
                    "logs:DescribeIndexPolicies",
                    "logs:DescribeResourcePolicies",
                ],
                "Resource": "*",
                "Condition": {"StringEquals": {"aws:RequestedRegion": region}},
            },
        ],
    }


if __name__ == "__main__":
    print(json.dumps(policy(load_config()), indent=2))
