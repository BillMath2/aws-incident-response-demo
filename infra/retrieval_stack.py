"""P06: private frozen corpus, S3 Vectors, Knowledge Base and pinned Guardrail."""

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct


class RetrievalStack(cdk.Stack):
    def __init__(self, scope: Construct, config: dict):
        super().__init__(
            scope,
            "incident-demo-retrieval",
            stack_name="incident-demo-retrieval",
            env=cdk.Environment(account=config["account"], region=config["region"]),
            termination_protection=True,
            synthesizer=cdk.DefaultStackSynthesizer(qualifier=config["bootstrap_qualifier"]),
        )
        account, region = config["account"], config["region"]
        bucket = f"incident-demo-artifacts-{account}-{region}"
        vector_name = f"incident-demo-vectors-{account}-{region}"
        vector_arn = f"arn:aws:s3vectors:{region}:{account}:bucket/{vector_name}"
        index_arn = vector_arn + "/index/runbooks-v1"
        vectors = cdk.CfnResource(
            self,
            "Vectors",
            type="AWS::S3Vectors::VectorBucket",
            properties={
                "VectorBucketName": vector_name,
                "EncryptionConfiguration": {"SseType": "AES256"},
                "Tags": [{"Key": "Project", "Value": "incident-demo"}],
            },
        )
        index = cdk.CfnResource(
            self,
            "Index",
            type="AWS::S3Vectors::Index",
            properties={
                "VectorBucketArn": vectors.get_att("VectorBucketArn").to_string(),
                "IndexName": "runbooks-v1",
                "DataType": "float32",
                "Dimension": 1024,
                "DistanceMetric": "cosine",
                "MetadataConfiguration": {
                    "NonFilterableMetadataKeys": [
                        "AMAZON_BEDROCK_TEXT",
                        "AMAZON_BEDROCK_METADATA",
                    ]
                },
                "Tags": [{"Key": "Project", "Value": "incident-demo"}],
            },
        )
        role = iam.Role(
            self,
            "KnowledgeRole",
            role_name="incident-demo-knowledge",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:bedrock:{region}:{account}:knowledge-base/"
                            + config.get("knowledge_base_id", "*")
                        )
                    },
                },
            ),
            inline_policies={
                "CorpusAndVectors": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["bedrock:InvokeModel"],
                            resources=[
                                f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
                            ],
                        ),
                        iam.PolicyStatement(
                            actions=["s3:ListBucket"],
                            resources=[f"arn:aws:s3:::{bucket}"],
                            conditions={"StringLike": {"s3:prefix": ["knowledge/p06-v1/*"]}},
                        ),
                        iam.PolicyStatement(
                            actions=["s3:GetObject"],
                            resources=[f"arn:aws:s3:::{bucket}/knowledge/p06-v1/*"],
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "s3vectors:" + action
                                for action in (
                                    "PutVectors",
                                    "GetVectors",
                                    "DeleteVectors",
                                    "QueryVectors",
                                    "GetIndex",
                                )
                            ],
                            resources=[index_arn],
                        ),
                    ]
                )
            },
        )
        kb = cdk.CfnResource(
            self,
            "KnowledgeBase",
            type="AWS::Bedrock::KnowledgeBase",
            properties={
                "Name": "incident-demo-runbooks",
                "RoleArn": role.role_arn,
                "KnowledgeBaseConfiguration": {
                    "Type": "VECTOR",
                    "VectorKnowledgeBaseConfiguration": {
                        "EmbeddingModelArn": (
                            f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
                        ),
                        "EmbeddingModelConfiguration": {
                            "BedrockEmbeddingModelConfiguration": {
                                "Dimensions": 1024,
                                "EmbeddingDataType": "FLOAT32",
                            }
                        },
                    },
                },
                "StorageConfiguration": {
                    "Type": "S3_VECTORS",
                    "S3VectorsConfiguration": {"IndexArn": index.get_att("IndexArn").to_string()},
                },
                "Tags": {"Project": "incident-demo", "Phase": "P06"},
            },
        )
        kb.node.add_dependency(role)
        source = cdk.CfnResource(
            self,
            "DataSource",
            type="AWS::Bedrock::DataSource",
            properties={
                "KnowledgeBaseId": kb.get_att("KnowledgeBaseId").to_string(),
                "Name": "frozen-runbooks-v1",
                "DataDeletionPolicy": "RETAIN",
                "DataSourceConfiguration": {
                    "Type": "S3",
                    "S3Configuration": {
                        "BucketArn": f"arn:aws:s3:::{bucket}",
                        "InclusionPrefixes": ["knowledge/p06-v1/"],
                    },
                },
                "VectorIngestionConfiguration": {
                    "ChunkingConfiguration": {"ChunkingStrategy": "NONE"}
                },
            },
        )
        guardrail = cdk.CfnResource(
            self,
            "Guardrail",
            type="AWS::Bedrock::Guardrail",
            properties={
                "Name": "incident-demo-boundaries",
                "Description": "P06 explicit input/source/output policy",
                "BlockedInputMessaging": "Content blocked by incident demo policy.",
                "BlockedOutputsMessaging": "Content blocked by incident demo policy.",
                "ContentPolicyConfig": {
                    "FiltersConfig": [
                        {
                            "Type": kind,
                            "InputStrength": "HIGH" if kind == "PROMPT_ATTACK" else "MEDIUM",
                            "OutputStrength": "NONE" if kind == "PROMPT_ATTACK" else "MEDIUM",
                        }
                        for kind in (
                            "HATE",
                            "INSULTS",
                            "SEXUAL",
                            "VIOLENCE",
                            "MISCONDUCT",
                            "PROMPT_ATTACK",
                        )
                    ]
                },
                "SensitiveInformationPolicyConfig": {
                    "RegexesConfig": [
                        {
                            "Name": "SyntheticSecret",
                            "Description": "Synthetic demo secret values only",
                            "Pattern": "DEMO_CANARY_[A-Za-z0-9]+",
                            "Action": "BLOCK",
                        }
                    ]
                },
                "Tags": [{"Key": "Project", "Value": "incident-demo"}],
            },
        )
        version = cdk.CfnResource(
            self,
            "GuardrailVersionV1",
            type="AWS::Bedrock::GuardrailVersion",
            properties={
                "GuardrailIdentifier": guardrail.get_att("GuardrailId").to_string(),
                "Description": "Frozen P06 v1 content/prompt-attack and synthetic-secret policy",
            },
        )
        for resource in (vectors, index, kb, source, guardrail, version):
            resource.apply_removal_policy(cdk.RemovalPolicy.RETAIN)
        cdk.Validations.of(role).acknowledge(
            cdk.Acknowledgment(
                id=f"AwsSolutions-IAM5[Resource::arn:aws:s3:::{bucket}/knowledge/p06-v1/*]",
                reason="Only the frozen corpus prefix is readable by this knowledge base role.",
            )
        )
        for name, value in {
            "KnowledgeBaseId": kb.get_att("KnowledgeBaseId").to_string(),
            "KnowledgeBaseArn": kb.get_att("KnowledgeBaseArn").to_string(),
            "DataSourceId": source.get_att("DataSourceId").to_string(),
            "GuardrailId": guardrail.get_att("GuardrailId").to_string(),
            "GuardrailArn": guardrail.get_att("GuardrailArn").to_string(),
            "GuardrailVersion": version.get_att("Version").to_string(),
            "VectorBucketName": vector_name,
            "IndexArn": index_arn,
            "SourceBucket": bucket,
        }.items():
            cdk.CfnOutput(self, name + "Output", value=value)
        cdk.Tags.of(self).add("Project", "incident-demo")
        cdk.Tags.of(self).add("Phase", "P06")
