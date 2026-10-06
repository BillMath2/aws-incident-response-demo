"""P05 runtime and diagnostic infrastructure; no action or approval capabilities."""

import json
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cloudtrail as cloudtrail
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as assets
from constructs import Construct

TOOLS = ("get_service_health", "get_recent_changes", "get_recent_logs")


class LiveStack(cdk.Stack):
    def __init__(
        self, scope: Construct, config: dict, package: Path, retrieval: dict | None = None
    ):
        super().__init__(
            scope,
            "incident-demo-live",
            stack_name="incident-demo-live",
            env=cdk.Environment(account=config["account"], region=config["region"]),
            termination_protection=True,
            synthesizer=cdk.DefaultStackSynthesizer(qualifier=config["bootstrap_qualifier"]),
        )
        account, region = config["account"], config["region"]
        artifact_bucket = f"incident-demo-artifacts-{account}-{region}"
        runtime_prefix = (
            f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/incident_demo_investigator*"
        )
        asset = assets.Asset(self, "Code", path=str(package))
        key = kms.Key(
            self,
            "LogsKey",
            description="incident-demo P05 runtime log encryption",
            enable_key_rotation=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
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
                        "kms:EncryptionContext:aws:logs:arn": [
                            f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/incident_demo_investigator*",
                            f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/incident-demo-diag-*",
                        ]
                    }
                },
            )
        )
        budget = dynamodb.Table(
            self,
            "Budget",
            table_name="incident-demo-live-budget",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            max_read_request_units=10,
            max_write_request_units=10,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True, recovery_period_in_days=7
            ),
            deletion_protection=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        functions = {}
        for tool in TOOLS:
            name = "incident-demo-diag-" + tool.removeprefix("get_").replace("_", "-")
            group = logs.LogGroup(
                self,
                tool + "Logs",
                log_group_name="/aws/lambda/" + name,
                retention=logs.RetentionDays.ONE_WEEK,
                encryption_key=key,
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )
            # Lambda execution-role assumption does not reliably supply SourceArn; scoped
            # pass-role and one role per function bind the deployment instead.
            role = iam.Role(
                self,
                tool + "Role",
                role_name=name,
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                inline_policies={
                    "OwnLogs": iam.PolicyDocument(
                        statements=[
                            iam.PolicyStatement(
                                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                                resources=[group.log_group_arn],
                            )
                        ]
                    )
                },
            )
            fn = lambda_.Function(
                self,
                tool,
                function_name=name,
                role=role,
                runtime=lambda_.Runtime.PYTHON_3_12,
                architecture=lambda_.Architecture.ARM_64,
                handler="incident_demo.live.diagnostics.handler",
                code=lambda_.Code.from_asset(str(package)),
                timeout=cdk.Duration.seconds(5),
                memory_size=256,
                log_group=group,
                environment={"TOOL_NAME": tool},
            )
            functions[tool] = fn.function_arn
            cdk.Validations.of(fn).acknowledge(
                cdk.Acknowledgment(
                    id="AwsSolutions-L1",
                    reason="Python 3.12 matches the locked application and ARM64 wheel build.",
                )
            )
        role = iam.Role(
            self,
            "InvestigatorRole",
            role_name="incident-demo-investigator",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": runtime_prefix},
                },
            ),
        )
        if retrieval:
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["bedrock:Retrieve"], resources=[retrieval["KnowledgeBaseArnOutput"]]
                )
            )
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["bedrock:ApplyGuardrail"], resources=[retrieval["GuardrailArnOutput"]]
                )
            )
        models = [
            f"arn:aws:bedrock:{r}::foundation-model/amazon.nova-{size}-v1:0"
            for r in ("us-east-1", "us-east-2", "us-west-2")
            for size in ("lite", "pro")
        ]
        profiles = [
            f"arn:aws:bedrock:{region}:{account}:inference-profile/us.amazon.nova-{size}-v1:0"
            for size in ("lite", "pro")
        ]
        for statement in [
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:CountTokens"], resources=models + profiles
            ),
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"], resources=list(functions.values())
            ),
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem", "dynamodb:PutItem"], resources=[budget.table_arn]
            ),
            iam.PolicyStatement(
                actions=["s3:PutObject"], resources=[f"arn:aws:s3:::{artifact_bucket}/runs/p06/*"]
            ),
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:GetObjectVersion"],
                resources=[f"arn:aws:s3:::{asset.s3_bucket_name}/{asset.s3_object_key}"],
            ),
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
                resources=[
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/incident_demo_investigator*:*"
                ],
            ),
        ]:
            role.add_to_policy(statement)
        for resource in (
            f"arn:aws:s3:::{artifact_bucket}/runs/p06/*",
            f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/"
            "runtimes/incident_demo_investigator*:*",
        ):
            cdk.Validations.of(role.node.find_child("DefaultPolicy")).acknowledge(
                cdk.Acknowledgment(
                    id=f"AwsSolutions-IAM5[Resource::{resource}]",
                    reason="Only project evidence objects or generated runtime log streams.",
                )
            )
        runtime = agentcore.CfnRuntime(
            self,
            "Runtime",
            agent_runtime_name="incident_demo_investigator",
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                    code=agentcore.CfnRuntime.CodeProperty(
                        s3=agentcore.CfnRuntime.S3LocationProperty(
                            bucket=asset.s3_bucket_name, prefix=asset.s3_object_key
                        )
                    ),
                    entry_point=["main.py"],
                    runtime="PYTHON_3_12",
                )
            ),
            role_arn=role.role_arn,
            protocol_configuration="HTTP",
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=60, max_lifetime=180
            ),
            environment_variables={
                "DIAGNOSTIC_FUNCTIONS": json.dumps(functions),
                "BUDGET_TABLE": budget.table_name,
                "ARTIFACT_BUCKET": artifact_bucket,
                "LANGSMITH_TRACING": "false",
                "AWS_MAX_ATTEMPTS": "1",
                **(
                    {
                        "KNOWLEDGE_BASE_ID": retrieval["KnowledgeBaseIdOutput"],
                        "GUARDRAIL_ID": retrieval["GuardrailIdOutput"],
                        "GUARDRAIL_VERSION": retrieval["GuardrailVersionOutput"],
                    }
                    if retrieval
                    else {}
                ),
            },
            tags={"Project": "incident-demo", "Phase": "P05"},
        )
        runtime.node.add_dependency(role)
        group = logs.LogGroup(
            self,
            "RuntimeLogs",
            log_group_name=f"/aws/bedrock-agentcore/runtimes/{runtime.attr_agent_runtime_id}-DEFAULT",
            retention=logs.RetentionDays.ONE_WEEK,
            encryption_key=key,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        smoke_group = logs.LogGroup(
            self,
            "SmokeLogs",
            log_group_name=f"/aws/bedrock-agentcore/runtimes/{runtime.attr_agent_runtime_id}-smoke",
            retention=logs.RetentionDays.ONE_WEEK,
            encryption_key=key,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        for label, monitored in (("Default", group), ("Smoke", smoke_group)):
            logs.MetricFilter(
                self,
                label + "Errors",
                log_group=monitored,
                metric_namespace="IncidentDemo/P05",
                metric_name="Failures",
                metric_value="1",
                filter_pattern=logs.FilterPattern.any(
                    logs.FilterPattern.string_value("$.event", "=", "runtime_failure"),
                    logs.FilterPattern.string_value("$.status", "=", "failed"),
                ),
            )
            logs.MetricFilter(
                self,
                label + "Latency",
                log_group=monitored,
                metric_namespace="IncidentDemo/P05",
                metric_name="WorkerLatencyMs",
                metric_value="$.worker_latency_ms",
                filter_pattern=logs.FilterPattern.string_value(
                    "$.event", "=", "investigation_finished"
                ),
            )
        for label, metric, threshold, statistic in (
            ("failures", "Failures", 1, "Sum"),
            ("latency", "WorkerLatencyMs", 110000, "Maximum"),
        ):
            cloudwatch.Alarm(
                self,
                label + "Alarm",
                alarm_name="incident-demo-p05-" + label,
                metric=cloudwatch.Metric(
                    namespace="IncidentDemo/P05",
                    metric_name=metric,
                    statistic=statistic,
                    period=cdk.Duration.minutes(1),
                ),
                threshold=threshold,
                evaluation_periods=1,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
        endpoint = agentcore.CfnRuntimeEndpoint(
            self,
            "Endpoint",
            agent_runtime_id=runtime.attr_agent_runtime_id,
            agent_runtime_version=runtime.attr_agent_runtime_version,
            name="smoke",
        )
        # CloudTrail management events plus only project Lambda/AgentCore data events.
        trail_bucket = s3.Bucket(
            self,
            "TrailBucket",
            bucket_name=f"incident-demo-trail-{account}-{region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=cdk.Duration.days(7))],
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        trail = cloudtrail.Trail(
            self,
            "Trail",
            trail_name="incident-demo-p05",
            bucket=trail_bucket,
            is_multi_region_trail=True,
            enable_file_validation=True,
            management_events=cloudtrail.ReadWriteType.ALL,
        )
        selectors = [
            {
                "Name": "Management",
                "FieldSelectors": [{"Field": "eventCategory", "Equals": ["Management"]}],
            },
            {
                "Name": "ProjectAgentCore",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {"Field": "resources.type", "Equals": ["AWS::BedrockAgentCore::Runtime"]},
                    {"Field": "resources.ARN", "StartsWith": [runtime_prefix.rstrip("*")]},
                ],
            },
            {
                "Name": "ProjectAgentCoreEndpoint",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {
                        "Field": "resources.type",
                        "Equals": ["AWS::BedrockAgentCore::RuntimeEndpoint"],
                    },
                    {"Field": "resources.ARN", "StartsWith": [runtime_prefix.rstrip("*")]},
                ],
            },
            {
                "Name": "ProjectLambda",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {"Field": "resources.type", "Equals": ["AWS::Lambda::Function"]},
                    {
                        "Field": "resources.ARN",
                        "StartsWith": [
                            f"arn:aws:lambda:{region}:{account}:function:incident-demo-diag-"
                        ],
                    },
                ],
            },
        ]
        if retrieval:
            for name in ("KnowledgeBase", "Guardrail"):
                selectors.append(
                    {
                        "Name": "P06" + name,
                        "FieldSelectors": [
                            {"Field": "eventCategory", "Equals": ["Data"]},
                            {"Field": "resources.type", "Equals": ["AWS::Bedrock::" + name]},
                            {"Field": "resources.ARN", "Equals": [retrieval[name + "ArnOutput"]]},
                        ],
                    }
                )
        trail.node.default_child.add_property_override("AdvancedEventSelectors", selectors)
        trail.node.default_child.add_property_deletion_override("EventSelectors")
        for construct, rule, reason in [
            (
                trail_bucket,
                "AwsSolutions-S1",
                "Audit log sink; recursive server access logging is avoided.",
            ),
            (
                trail,
                "AwsSolutions-CT2",
                "Synthetic demo trail uses SSE-S3; runtime log groups use a customer KMS key.",
            ),
            (
                trail,
                "AwsSolutions-CT3",
                "Seven-day S3 evidence is inspected by the verifier; no SNS recipients configured.",
            ),
            (
                role,
                "AwsSolutions-IAM5",
                "Generated runtime log streams and the project evidence prefix require wildcards.",
            ),
        ]:
            cdk.Validations.of(construct).acknowledge(cdk.Acknowledgment(id=rule, reason=reason))
        for name, value in {
            "RuntimeArn": runtime.attr_agent_runtime_arn,
            "RuntimeId": runtime.attr_agent_runtime_id,
            "EndpointArn": endpoint.attr_agent_runtime_endpoint_arn,
            "RuntimeLogGroup": group.log_group_name,
            "BudgetTable": budget.table_name,
            "InvestigatorRole": role.role_arn,
            "LogsKeyArn": key.key_arn,
            "TrailBucket": trail_bucket.bucket_name,
            **{k: v for k, v in functions.items()},
        }.items():
            cdk.CfnOutput(self, name + "Output", value=value)
        cdk.Tags.of(self).add("Project", "incident-demo")
        cdk.Tags.of(self).add("Phase", "P05")
