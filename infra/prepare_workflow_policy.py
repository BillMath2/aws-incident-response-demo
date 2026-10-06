"""Project deployment permissions for P07, validated before installation."""

from deployment_policy import policy as foundation
from live_deployment_policy import policy as live
from manage import verify_identity
from prepare_live_policy import install
from settings import load_config

TAG_EXCEPTION = ("INVALID_ACTION", "The action apigateway:TagResource does not exist.")


def policy(config):
    account, region = config["account"], config["region"]
    api_path = f"arn:aws:apigateway:{region}::/apis/" + config["workflow_api_id"]
    old = live(config)["Statement"]
    base = {s["Sid"]: s for s in foundation(config)["Statement"]}
    statements = []

    def allow(actions, resources, conditions=None):
        item = {"Effect": "Allow", "Action": actions, "Resource": resources}
        if conditions:
            item["Condition"] = conditions
        statements.append(item)

    roles = [f"arn:aws:iam::{account}:role/incident-demo-p07-*"]
    allow(next(s["Action"] for s in old if "iam:CreateRole" in s["Action"]), roles)
    allow(
        ["iam:PassRole"],
        roles,
        {
            "StringEquals": {
                "iam:PassedToService": [
                    "lambda.amazonaws.com",
                    "states.amazonaws.com",
                    "events.amazonaws.com",
                ]
            }
        },
    )
    allow(
        next(s["Action"] for s in old if "lambda:CreateFunction" in s["Action"])
        + [
            "lambda:AddPermission",
            "lambda:RemovePermission",
            "lambda:GetPolicy",
            "lambda:PutFunctionEventInvokeConfig",
            "lambda:GetFunctionEventInvokeConfig",
            "lambda:DeleteFunctionEventInvokeConfig",
        ],
        [
            f"arn:aws:lambda:{region}:{account}:function:incident-demo-p07-*",
            f"arn:aws:lambda:{region}:{account}:function:incident-demo-executor",
            f"arn:aws:lambda:{region}:{account}:function:incident-demo-executor:$LATEST",
        ],
    )
    allow(
        base["FoundationTable"]["Action"],
        [f"arn:aws:dynamodb:{region}:{account}:table/incident-demo-p07-*"],
    )
    allow(
        base["FoundationLogGroup"]["Action"] + ["logs:AssociateKmsKey"],
        [f"arn:aws:logs:{region}:{account}:log-group:/incident-demo/p07/*"],
    )
    allow(
        [
            "states:" + a
            for a in (
                "CreateStateMachine",
                "UpdateStateMachine",
                "DeleteStateMachine",
                "DescribeStateMachine",
                "TagResource",
                "UntagResource",
                "ListTagsForResource",
            )
        ],
        [f"arn:aws:states:{region}:{account}:stateMachine:incident-demo-p07"],
    )
    allow(
        [
            "sqs:" + a
            for a in (
                "CreateQueue",
                "DeleteQueue",
                "GetQueueAttributes",
                "GetQueueUrl",
                "SetQueueAttributes",
                "TagQueue",
                "UntagQueue",
                "ListQueueTags",
            )
        ],
        [f"arn:aws:sqs:{region}:{account}:incident-demo-p07-dlq"],
    )
    allow(
        [
            "events:" + a
            for a in (
                "CreateEventBus",
                "DescribeEventBus",
                "UpdateEventBus",
                "DeleteEventBus",
                "CreateSubscriber",
                "DescribeSubscriber",
                "UpdateSubscriber",
                "DeleteSubscriber",
                "TagResource",
                "UntagResource",
                "ListTagsForResource",
                "PutRule",
                "DescribeRule",
                "DeleteRule",
                "PutTargets",
                "RemoveTargets",
                "ListTargetsByRule",
            )
        ],
        [
            f"arn:aws:events:{region}:{account}:event-busv2/incident-demo-p07/*",
            f"arn:aws:events:{region}:{account}:subscriber/incident-demo-p07-*/*",
            f"arn:aws:events:{region}:{account}:rule/incident-demo-p07-*",
        ],
    )
    allow(
        ["apigateway:POST"],
        [f"arn:aws:apigateway:{region}::/apis"],
        {
            "StringEquals": {
                "apigateway:Request/ApiName": "incident-demo-p07",
                "aws:RequestTag/Project": "incident-demo",
                "aws:RequestTag/Phase": "P07",
            }
        },
    )
    allow(
        ["apigateway:GET"],
        [api_path, api_path + "/*"],
    )
    allow(
        ["apigateway:POST", "apigateway:PATCH", "apigateway:DELETE", "apigateway:PUT"],
        [api_path, api_path + "/*"],
    )
    # TagResource maps to HTTP verbs on a separate tags path. Its ARN embeds the API ID.
    allow(
        ["apigateway:GET", "apigateway:POST", "apigateway:PATCH", "apigateway:PUT"],
        [f"arn:aws:apigateway:{region}::/tags/*" + config["workflow_api_id"] + "*"],
    )
    # No KMS permissions are added by P07. The previously installed P05 policy already
    # limits key creation/management to Project=incident-demo and us-east-2.
    # Live CreateStage repeatedly requested this literal permission even though Access
    # Analyzer's action catalog rejects it. Scope the retained exception to this stage only.
    allow(["apigateway:TagResource"], [api_path + "/stages", api_path + "/stages/*"])
    # Account-level log-delivery permission was rejected by automatic approval review.
    # API request auditing uses the existing private Lambda logs and gateway metrics.
    allow(
        [
            "cloudwatch:PutMetricAlarm",
            "cloudwatch:DeleteAlarms",
            "cloudwatch:DescribeAlarms",
            "cloudwatch:TagResource",
            "cloudwatch:UntagResource",
            "cloudwatch:ListTagsForResource",
        ],
        [f"arn:aws:cloudwatch:{region}:{account}:alarm:incident-demo-p07-*"],
    )
    return {"Version": "2012-10-17", "Statement": statements}


def main():
    config = load_config()
    verify_identity(config)
    install(
        config,
        policy(config),
        "incident-demo-p07-cfn-execution",
        "cfn-execution-policy",
        "p07",
        validation_exceptions=(TAG_EXCEPTION,),
    )


if __name__ == "__main__":
    main()
