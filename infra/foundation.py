"""Storage foundation only. Runtime identities and workflow are later packages."""

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct


class Foundation(cdk.Stack):
    def __init__(self, scope: Construct, config: dict):
        super().__init__(
            scope,
            config["stack_name"],
            stack_name=config["stack_name"],
            env=cdk.Environment(account=config["account"], region=config["region"]),
            termination_protection=True,
            synthesizer=cdk.DefaultStackSynthesizer(qualifier=config["bootstrap_qualifier"]),
            description="P04 incident-demo storage foundation; no investigator or executor",
        )
        suffix = f"{config['account']}-{config['region']}"
        access_logs = s3.Bucket(
            self,
            "AccessLogs",
            bucket_name=f"incident-demo-access-logs-{suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            enforce_ssl=True,
            lifecycle_rules=[cdk_s3_expiry("ExpireAccessLogs", days=7)],
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        cdk.Validations.of(access_logs).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions-S1", reason="Access-log sink; recursive logging is avoided."
            )
        )
        artifacts = s3.Bucket(
            self,
            "Artifacts",
            bucket_name=f"incident-demo-artifacts-{suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            enforce_ssl=True,
            versioned=True,
            server_access_logs_bucket=access_logs,
            server_access_logs_prefix="artifacts/",
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="ExpireRunEvidence",
                    prefix="runs/",
                    expiration=cdk.Duration.days(30),
                    noncurrent_version_expiration=cdk.Duration.days(7),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                ),
                s3.LifecycleRule(
                    id="ExpireSmokeEvidence",
                    prefix="smoke/",
                    expiration=cdk.Duration.days(1),
                    noncurrent_version_expiration=cdk.Duration.days(1),
                ),
            ],
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        state = dynamodb.Table(
            self,
            "State",
            table_name="incident-demo-state",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            max_read_request_units=10,
            max_write_request_units=10,
            encryption=dynamodb.TableEncryption.DEFAULT,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True, recovery_period_in_days=7
            ),
            time_to_live_attribute="expires_at",
            deletion_protection=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        audit = logs.LogGroup(
            self,
            "AuditLogs",
            log_group_name="/incident-demo/foundation",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        for key, value in {
            "Project": "incident-demo",
            "Environment": "demo",
            "Phase": "P04",
        }.items():
            cdk.Tags.of(self).add(key, value)
        for key, value in {
            "ArtifactBucket": artifacts.bucket_name,
            "AccessLogBucket": access_logs.bucket_name,
            "StateTable": state.table_name,
            "AuditLogGroup": audit.log_group_name,
        }.items():
            cdk.CfnOutput(self, key, value=value)


def cdk_s3_expiry(identifier: str, days: int) -> s3.LifecycleRule:
    return s3.LifecycleRule(
        id=identifier,
        expiration=cdk.Duration.days(days),
        abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
    )
