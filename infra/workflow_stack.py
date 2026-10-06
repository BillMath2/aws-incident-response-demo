"""P07: IAM HTTP API, durable outboxes, Standard workflow and isolated sandbox executor."""

import json
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct


class WorkflowStack(cdk.Stack):
    def __init__(self, scope: Construct, config: dict, package: Path, live: dict, request: dict):
        super().__init__(
            scope,
            "incident-demo-workflow",
            stack_name="incident-demo-workflow",
            env=cdk.Environment(account=config["account"], region=config["region"]),
            termination_protection=True,
            synthesizer=cdk.DefaultStackSynthesizer(qualifier=config["bootstrap_qualifier"]),
        )
        account, region = config["account"], config["region"]

        def arn(service, resource):
            return f"arn:aws:{service}:{region}:{account}:{resource}"

        key = kms.Key(
            self, "LogsKey", enable_key_rotation=True, removal_policy=cdk.RemovalPolicy.RETAIN
        )
        key.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal(f"logs.{region}.amazonaws.com")],
                actions=[
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:DescribeKey",
                ],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "kms:EncryptionContext:aws:logs:arn": arn(
                            "logs", "log-group:/incident-demo/p07/*"
                        )
                    }
                },
            )
        )

        def group(name):
            return logs.LogGroup(
                self,
                name + "Logs",
                log_group_name="/incident-demo/p07/" + name,
                encryption_key=key,
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )

        tables = {}
        for name in ("runs", "approvals", "sandbox"):
            tables[name] = ddb.Table(
                self,
                name + "Table",
                table_name="incident-demo-p07-" + name,
                partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
                billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                max_read_request_units=10,
                max_write_request_units=10,
                encryption=ddb.TableEncryption.AWS_MANAGED,
                deletion_protection=True,
                removal_policy=cdk.RemovalPolicy.RETAIN,
                point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                    point_in_time_recovery_enabled=True, recovery_period_in_days=7
                ),
            )
        dlq = sqs.Queue(
            self,
            "DeadLetters",
            queue_name="incident-demo-p07-dlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            retention_period=cdk.Duration.days(7),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        cdk.Validations.of(dlq).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-SQS3",
                reason="This is the final dead-letter queue; recovery is explicit and bounded.",
            )
        )
        bus = cdk.CfnResource(
            self,
            "Bus",
            type="AWS::EventsV2::EventBus",
            properties={
                "Name": "incident-demo-p07",
                "StorageConfiguration": {"RetentionPeriodInDays": 1},
                "Tags": [{"Key": "Project", "Value": "incident-demo"}],
            },
        )
        bus.apply_removal_policy(cdk.RemovalPolicy.RETAIN)
        machine_arn = arn("states", "stateMachine:incident-demo-p07")
        role_arns = {
            name: f"arn:aws:iam::{account}:role/incident-demo-p07-{name}"
            for name in ("analyst", "approver", "tester")
        }
        environment = {name.upper() + "_TABLE": t.table_name for name, t in tables.items()} | {
            "BUCKET": f"incident-demo-artifacts-{account}-{region}",
            "BUS_ARN": bus.ref,
            "MACHINE_ARN": machine_arn,
            "DLQ_URL": dlq.queue_url,
            "RUNTIME_ARN": live["RuntimeArnOutput"],
            "LIVE_REQUEST": json.dumps(request),
            **{k.upper() + "_ROLE": v for k, v in role_arns.items()},
        }
        functions = {}
        for name, handler in {
            "intake": "api",
            "decision": "api",
            "read": "api",
            "dispatch": "dispatch",
            "starter": "starter",
            "bridge": "investigate",
            "register": "register",
            "callbacks": "recover_callbacks",
            "executor": "execute",
            "observe": "observe",
            "finish": "finish",
        }.items():
            log = group(name)
            role = iam.Role(
                self,
                name + "Role",
                role_name="incident-demo-p07-" + name,
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            )
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[log.log_group_arn],
                )
            )
            functions[name] = lam.Function(
                self,
                name,
                role=role,
                function_name="incident-demo-executor"
                if name == "executor"
                else "incident-demo-p07-" + name,
                code=lam.Code.from_asset(str(package)),
                runtime=lam.Runtime.PYTHON_3_12,
                architecture=lam.Architecture.ARM_64,
                memory_size=256,
                timeout=cdk.Duration.seconds(150 if name == "bridge" else 30),
                handler="incident_demo.workflow.handlers." + handler,
                environment=environment,
                log_group=log,
                retry_attempts=0,
            )
            cdk.Validations.of(functions[name]).acknowledge(
                cdk.Acknowledgment(
                    id="AwsSolutions-L1", reason="Python 3.12 matches locked ARM64 dependencies."
                )
            )

        def allow(name, actions, resources, conditions=None):
            functions[name].add_to_role_policy(
                iam.PolicyStatement(actions=actions, resources=resources, conditions=conditions)
            )

        def access(name, table, prefixes, write=False, scan=False):
            actions = ["dynamodb:GetItem"] + (
                ["dynamodb:PutItem", "dynamodb:ConditionCheckItem"] if write else []
            )
            allow(
                name,
                actions,
                [tables[table].table_arn],
                {
                    "ForAllValues:StringLike": {"dynamodb:LeadingKeys": prefixes},
                    "Null": {"dynamodb:LeadingKeys": "false"},
                },
            )
            if scan:
                allow(name, ["dynamodb:Scan"], [tables[table].table_arn])

        access("intake", "runs", ["request#*", "run#*", "dispatch#*", "batch#p07-dev-01"], True)
        access("intake", "sandbox", ["service#*"], True)
        access("read", "runs", ["run#*"])
        for name in ("decision", "callbacks"):
            access(name, "runs", ["run#*"], True)
            access(name, "approvals", ["p07-*"], True, name == "callbacks")
            allow(name, ["states:SendTaskSuccess"], ["*"])
            cdk.Validations.of(functions[name].role).acknowledge(
                cdk.Acknowledgment(
                    id="AwsSolutions-IAM5[Resource::*]",
                    reason="SendTaskSuccess has no resource-level IAM support; tokens are private.",
                )
            )
        for name in ("dispatch", "starter"):
            access(name, "runs", ["run#*", "dispatch#*"], True, name == "dispatch")
        # Dispatcher finalization needs only missing approval/receipt reads for pending runs.
        access("dispatch", "approvals", ["p07-*"])
        access("dispatch", "sandbox", ["receipt#*"])
        access("callbacks", "sandbox", ["receipt#*"])
        allow("dispatch", ["events:PutEvents"], [bus.ref])
        dlq.grant_send_messages(functions["dispatch"])
        allow("starter", ["states:StartExecution"], [machine_arn])
        for name in ("bridge", "finish", "observe"):
            access(name, "runs", ["run#*", "invocation#*"], True)
            access(name, "approvals", ["p07-*"], True)
            access(name, "sandbox", ["receipt#*", "service#*"])
        access("register", "runs", ["run#*"], True)
        access("register", "approvals", ["p07-*"], True)
        access("executor", "runs", ["run#*"])
        allow(
            "executor",
            ["dynamodb:ConditionCheckItem"],
            [tables["runs"].table_arn],
            {
                "ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["run#*"]},
                "Null": {"dynamodb:LeadingKeys": "false"},
            },
        )
        # The executor cannot write run/proposal documents; it only condition-checks their version.
        # IAM explicit deny also protects this boundary if future grants expand.
        functions["executor"].add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                actions=["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
                resources=[tables["runs"].table_arn],
            )
        )
        access("executor", "approvals", ["p07-*"], True)
        access("executor", "sandbox", ["service#*", "receipt#*"], True)
        allow(
            "bridge",
            ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:StopRuntimeSession"],
            [live["RuntimeArnOutput"], live["EndpointArnOutput"]],
        )
        bucket_arn = "arn:aws:s3:::" + environment["BUCKET"]
        for name in ("bridge", "observe"):
            suffix = "investigation.json" if name == "bridge" else "verification.json"
            allow(name, ["s3:GetObject", "s3:PutObject"], [bucket_arn + "/runs/p07/*/" + suffix])
            cdk.Validations.of(functions[name].role).acknowledge(
                cdk.Acknowledgment(
                    id="AwsSolutions-IAM5[Resource::" + bucket_arn + "/runs/p07/*/" + suffix + "]",
                    reason="Immutable run artifacts use generated run IDs within fixed prefixes.",
                )
            )
        allow("bridge", ["s3:GetObject"], [bucket_arn + "/runs/p06/p07-*.json"])
        allow("read", ["s3:GetObject"], [bucket_arn + "/runs/p07/*/investigation.json"])
        allow(
            "read",
            ["s3:ListBucket"],
            [bucket_arn],
            {"StringLike": {"s3:prefix": "runs/p07/*/investigation.json"}},
        )
        cdk.Validations.of(functions["read"].role).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-IAM5[Resource::" + bucket_arn + "/runs/p07/*/investigation.json]",
                reason="Reviewers read this demo's immutable investigation artifacts.",
            )
        )
        cdk.Validations.of(functions["bridge"].role).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-IAM5[Resource::" + bucket_arn + "/runs/p06/p07-*.json]",
                reason="Read only P07 run artifacts persisted by the existing investigator.",
            )
        )
        # No ListBucket grant: missing known keys may return 403; use a narrow prefix condition.
        for name in ("bridge", "observe"):
            allow(
                name,
                ["s3:ListBucket"],
                [bucket_arn],
                {"StringLike": {"s3:prefix": ["runs/p06/p07-*", "runs/p07/*"]}},
            )

        machine_role = iam.Role(
            self,
            "MachineRole",
            role_name="incident-demo-p07-machine",
            assumed_by=iam.ServicePrincipal(
                "states.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnEquals": {"aws:SourceArn": machine_arn},
                },
            ),
        )
        machine_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    functions[n].function_arn
                    for n in ("bridge", "register", "executor", "observe", "finish")
                ],
            )
        )
        machine_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogDelivery",
                    "logs:GetLogDelivery",
                    "logs:UpdateLogDelivery",
                    "logs:DeleteLogDelivery",
                    "logs:ListLogDeliveries",
                    "logs:PutResourcePolicy",
                    "logs:DescribeResourcePolicies",
                    "logs:DescribeLogGroups",
                ],
                resources=["*"],
            )
        )
        cdk.Validations.of(machine_role).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-IAM5[Resource::*]",
                reason="CloudWatch Logs delivery APIs require Resource *. No history access.",
            )
        )
        retry = [
            {
                "ErrorEquals": [
                    "Lambda.ServiceException",
                    "Lambda.AWSLambdaException",
                    "Lambda.SdkClientException",
                    "Lambda.TooManyRequestsException",
                ],
                "IntervalSeconds": 5,
                "MaxAttempts": 1,
                "BackoffRate": 1,
            }
        ]

        def task(name, next_state, timeout=35, parameters=None):
            return {
                "Type": "Task",
                "Resource": functions[name].function_arn,
                "TimeoutSeconds": timeout,
                "Parameters": parameters or {"run_id.$": "$.run_id"},
                "Retry": retry,
                "Catch": [
                    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": "Failed"}
                ],
                "Next": next_state,
            }

        states = {
            "Investigate": task("bridge", "Proposal?", 160),
            "Proposal?": {
                "Type": "Choice",
                "Choices": [
                    {"Variable": "$.proposal_ready", "BooleanEquals": True, "Next": "Approval"}
                ],
                "Default": "Done",
            },
            "Approval": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
                "Parameters": {
                    "FunctionName": functions["register"].function_arn,
                    "Payload": {"run_id.$": "$.run_id", "token.$": "$$.Task.Token"},
                },
                "TimeoutSecondsPath": "$.wait_seconds",
                "Next": "Approved?",
                "Catch": [
                    {
                        "ErrorEquals": ["States.Timeout"],
                        "ResultPath": "$.failure",
                        "Next": "Expired",
                    },
                    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": "Failed"},
                ],
            },
            "Approved?": {
                "Type": "Choice",
                "Choices": [
                    {"Variable": "$.decision", "StringEquals": "approved", "Next": "Execute"}
                ],
                "Default": "Rejected",
            },
            "Execute": task("executor", "Observe"),
            "Observe": task("observe", "Done"),
            "Done": {"Type": "Succeed"},
        }
        for label, status in (
            ("Failed", "failed"),
            ("Expired", "expired"),
            ("Rejected", "rejected"),
        ):
            states[label] = task(
                "finish", "Done", parameters={"run_id.$": "$.run_id", "status": status}
            )
            states[label].pop("Catch")
        machine_log = group("workflow")
        machine_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[machine_log.log_group_arn],
            )
        )
        machine = sfn.CfnStateMachine(
            self,
            "Machine",
            state_machine_name="incident-demo-p07",
            state_machine_type="STANDARD",
            role_arn=machine_role.role_arn,
            definition={"StartAt": "Investigate", "TimeoutSeconds": 1200, "States": states},
            logging_configuration=sfn.CfnStateMachine.LoggingConfigurationProperty(
                level="ALL",
                include_execution_data=False,
                destinations=[
                    sfn.CfnStateMachine.LogDestinationProperty(
                        cloud_watch_logs_log_group=sfn.CfnStateMachine.CloudWatchLogsLogGroupProperty(
                            log_group_arn=machine_log.log_group_arn
                        )
                    )
                ],
            ),
        )
        cdk.Validations.of(machine).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-SF2",
                reason="Private history and metadata-only CloudWatch logs provide a trace.",
            )
        )
        machine.node.add_dependency(machine_role.node.find_child("DefaultPolicy"))
        delivery = iam.Role(
            self,
            "DeliveryRole",
            role_name="incident-demo-p07-delivery",
            assumed_by=iam.ServicePrincipal(
                "events.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": account}}
            ),
        )
        functions["starter"].grant_invoke(delivery)
        cdk.Validations.of(delivery).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-IAM5[Resource::<"
                + self.get_logical_id(functions["starter"].node.default_child)
                + ".Arn>:*]",
                reason="CDK invoke grant includes versions of only the starter function.",
            )
        )
        dlq.grant_send_messages(delivery)
        subscriber = cdk.CfnResource(
            self,
            "Subscriber",
            type="AWS::EventsV2::Subscriber",
            properties={
                "Name": "incident-demo-p07-start",
                "EventBusArn": bus.ref,
                "State": "RUNNING",
                "Type": "UNORDERED",
                "StartingPosition": "LATEST",
                "BatchConfiguration": {"MaxBatchSize": 1},
                "Transformer": {"Type": "RAW"},
                "FilterConfiguration": {
                    "Filters": [
                        {
                            "Scope": "DATA",
                            "Pattern": json.dumps(
                                {"source": ["incident.demo"], "detail-type": ["IncidentAccepted"]}
                            ),
                        }
                    ]
                },
                "InvokeConfiguration": {
                    "RoleArn": delivery.role_arn,
                    "TargetArn": functions["starter"].function_arn,
                    "LambdaParameters": {
                        "InvocationType": "REQUEST_RESPONSE",
                        "InvocationTimeoutSeconds": "30",
                    },
                },
                "RetryPolicy": {"MaxRetryAttempts": 1, "MaxEventAgeInSeconds": 60},
                "OnFailureConfiguration": {"Arn": dlq.queue_arn},
                "LogConfiguration": {"Level": "OFF"},
            },
        )
        subscriber.node.add_dependency(machine, delivery)
        subscriber.node.add_dependency(delivery.node.find_child("DefaultPolicy"))
        for resource in (bus, subscriber):
            cdk.Validations.of(resource).acknowledge(
                cdk.Acknowledgment(
                    id="CloudFormation-Validate::F3006",
                    reason="Ohio DescribeType verified both EventsV2 types on 2026-10-06.",
                )
            )
        for name in ("dispatch", "callbacks"):
            rule = events.Rule(
                self,
                name + "Schedule",
                rule_name="incident-demo-p07-" + name,
                schedule=events.Schedule.rate(cdk.Duration.minutes(1)),
            )
            rule.add_target(
                targets.LambdaFunction(
                    functions[name],
                    retry_attempts=1,
                    max_event_age=cdk.Duration.minutes(2),
                    dead_letter_queue=dlq,
                )
            )
        api = apigw.CfnApi(self, "Api", name="incident-demo-p07", protocol_type="HTTP")
        group("api")  # Retained empty destination; gateway delivery permission is not provisioned.
        stage = apigw.CfnStage(
            self,
            "Stage",
            api_id=api.ref,
            stage_name="$default",
            auto_deploy=True,
            default_route_settings=apigw.CfnStage.RouteSettingsProperty(
                throttling_burst_limit=2, throttling_rate_limit=1, detailed_metrics_enabled=True
            ),
        )
        cdk.Validations.of(stage).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-APIG1",
                reason=(
                    "Account-level delivery permission was rejected. Private integration Lambda "
                    "request audits and API metrics are enabled; pre-integration rejects have "
                    "no per-request server log. See docs/p07-live-runbook.md."
                ),
            )
        )
        for route, name in {
            "POST /incidents": "intake",
            "POST /control-tests": "intake",
            "GET /runs/{run_id}": "read",
            "POST /runs/{run_id}/decision": "decision",
        }.items():
            identifier = route.replace("/", "").replace(" ", "").replace("{", "").replace("}", "")
            integration = apigw.CfnIntegration(
                self,
                identifier + "Integration",
                api_id=api.ref,
                integration_type="AWS_PROXY",
                integration_uri=functions[name].function_arn,
                payload_format_version="2.0",
                timeout_in_millis=10000,
            )
            apigw.CfnRoute(
                self,
                identifier + "Route",
                api_id=api.ref,
                route_key=route,
                authorization_type="AWS_IAM",
                target="integrations/" + integration.ref,
            )
            functions[name].add_permission(
                identifier + "ApiPermission",
                principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
                source_arn=arn(
                    "execute-api", api.ref + "/*/" + route.replace(" ", "").replace("{run_id}", "*")
                ),
            )
        for name in role_arns:
            role = iam.Role(
                self,
                name + "UserRole",
                role_name="incident-demo-p07-" + name,
                assumed_by=iam.ArnPrincipal(config["operator_role_arn"]),
                max_session_duration=cdk.Duration.hours(1),
            )
            paths = ["GET/runs/*"] if name != "tester" else []
            paths += (
                ["POST/incidents"]
                if name == "analyst"
                else (["POST/runs/*/decision"] if name == "approver" else ["POST/control-tests"])
            )
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["execute-api:Invoke"],
                    resources=[arn("execute-api", api.ref + "/*/" + path) for path in paths],
                )
            )
            for path in paths:
                cdk.Validations.of(role).acknowledge(
                    cdk.Acknowledgment(
                        id="AwsSolutions-IAM5[Resource::"
                        + arn("execute-api", "<" + self.get_logical_id(api) + ">/*/" + path)
                        + "]",
                        reason="Fixed API, HTTP method and route; generated run IDs vary.",
                    )
                )
        cw.Alarm(
            self,
            "WorkflowFailureAlarm",
            alarm_name="incident-demo-p07-failed",
            metric=cw.Metric(
                namespace="AWS/States",
                metric_name="ExecutionsFailed",
                statistic="Sum",
                dimensions_map={"StateMachineArn": machine_arn},
            ),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        cw.Alarm(
            self,
            "DeadLetterAlarm",
            alarm_name="incident-demo-p07-deadletters",
            metric=dlq.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        for name, value in {
            "ApiUrl": api.attr_api_endpoint,
            "MachineArn": machine_arn,
            "BusArn": bus.ref,
            "SubscriberArn": subscriber.ref,
            "DeadLetterUrl": dlq.queue_url,
            **{k.title() + "Role": v for k, v in role_arns.items()},
            **{k.title() + "Table": v.table_name for k, v in tables.items()},
        }.items():
            cdk.CfnOutput(self, name + "Output", value=value)
        cdk.Tags.of(self).add("Project", "incident-demo")
        cdk.Tags.of(self).add("Phase", "P07")
