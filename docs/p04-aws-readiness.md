# P04 AWS readiness and foundation

Target: account `498084841421`, profile `incident-demo`, region `us-east-2` (Ohio).
Decisions and prices checked October 5, 2026. This package prepares the cloud foundation;
it does not claim a deployed investigator, retrieval, filtering, or approval workflow.

## Account and region

The initial `us-east-1` checks were denied by organization policy `p-3kv3dnyq`
(`AdvancedModeRegionRestrictionSecurityControlPolicy`). Its regional conditions restrict
infrastructure operations in Virginia and Oregon, while allowing selected Bedrock inference
operations. Read-only checks in Ohio passed. No SCP was changed.

The `org-admin` profile ultimately authenticated to account `475666097120`, which could read
the policy; it is not the organization's management account (`147741822103`). Deployment
uses only the demo account. `infra/manage.py` checks STS identity and always supplies the
configured profile and region. It refuses a mismatched account, and the application rejects
a region other than the verified Ohio target. Ambient AWS profile/region settings cannot
silently redirect these commands.

## Model and feature decisions

The versioned selection is [infra/models.json](../infra/models.json). The models are inexpensive
baseline candidates for the required controlled comparison, not a claim that they are the
best current models. Both investigation models use the same Converse interface, token limits,
tools, and output validation. P05 must verify tool use and contract conformance with actual
development cases before freezing the evaluation candidate.

| Purpose | Selected identifier | Routing / validation |
|---|---|---|
| V0/V1/V2 base model | `us.amazon.nova-lite-v1:0` | US geographic inference profile |
| Second-model comparison | `us.amazon.nova-pro-v1:0` | Same interface; quality unmeasured |
| Separate judge | `us.meta.llama3-3-70b-instruct-v1:0` | Different model family; never authorizes actions |
| Runbook embeddings | `amazon.titan-embed-text-v2:0` | Ohio, 1,024 floating-point dimensions |
| Retrieval | Customer-managed Bedrock Knowledge Base + S3 Vectors | Semantic search, cosine distance; P06 creation |
| Investigator runtime | AgentCore Runtime with LangGraph, HTTP protocol | P05 health/invocation tests pending |
| Guardrails | Bedrock ApplyGuardrail at input, source and output boundaries | P06 policy creation and boundary tests pending |

The three inference profiles currently list Virginia, Ohio, and Oregon destinations.
Requests originate in Ohio but model processing may occur in any of those US regions;
this is **not** Ohio-only data processing. No global profile is selected. Foundation storage
stays in Ohio. Recheck destinations before provisioning the investigator IAM role.
[Inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)
and [model capability catalog](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html).

Bill explicitly selected S3 Vectors in Ohio. The newer fully Managed Knowledge Base is not
listed for Ohio, so the project uses the `VECTOR` knowledge-base type and owns its vector
store. S3 Vectors supports semantic search; do not request hybrid search. Keep chunk metadata
within the supported limits and validate document/version/owner/freshness fields during P06.
No embedding index or ingestion is provisioned in P04.
[Managed KB regions](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-regions.html),
[S3 Vectors integration](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html),
[S3 Vectors regions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-regions-quotas.html).

## Permission matrix

Only the CDK bootstrap identities and its restricted execution policy belong to P04.
Application identities below are the implementation contract for P05-P07; listing them
here does not prove effective isolation. Create roles when their actual resources exist,
derive service role trust from SourceAccount/SourceArn, and prove denial at runtime.

| Identity | Intended access | Excluded from that identity |
|---|---|---|
| Local deployer | Bootstrap and assume project CDK roles in the demo account | Management-account deployment; SCP changes |
| CloudFormation execution | Named foundation buckets, table and log group | IAM administration, model use, unrelated resources |
| Intake | Conditional request/outbox transaction | Approve; execute rollback |
| Dispatcher | Pending dispatch records and named EventBridge bus | Approve; mutate service release |
| Investigator | Selected model/profile ARNs, diagnostics, retrieval and guardrails | Approval records, callback tokens, executor, service mutation |
| Diagnostic Lambda | Synthetic telemetry and its own logs | Approval and service mutation |
| Knowledge Base | Read runbook prefix, invoke embedding model, access named vector index | Evaluator corpus, approvals, action receipts |
| Authenticated analyst | Submit/read own demo runs through controlled API | Approve own investigation; execute |
| Authenticated approver | Decide stored proposals through approval endpoint | Arbitrary action arguments; direct execution |
| Approval handler | Store bound decision and call matching workflow callback | Service release mutation |
| Executor | Conditional transaction on proposal, consumed approval, service and receipt keys | Model calls; policy administration |
| Workflow | Invoke named handlers and runtime; callback orchestration | Arbitrary Lambda invocation or model-selected targets |

The complete P04 deployment policy is generated by
[deployment_policy.py](../infra/deployment_policy.py) and retained as
[cfn-execution-policy.json](evidence/p04/cfn-execution-policy.json). Its five statements manage
the two exact S3 buckets, the exact state table, the exact log group, and regional log-group
discovery, plus read the exact project CDK bootstrap-version parameter. AWS-listed dependent
table actions are limited to that same table. The policy
contains no `iam:*`, Organizations, model-invocation, or wildcard-service permission.
The sole resource `*` statement is regional log discovery (`DescribeLogGroups`,
`DescribeIndexPolicies`, `DescribeResourcePolicies`), required by CloudFormation's current
log-group read handler. `GetDataProtectionPolicy` is limited to the foundation log group.

CDK's standard bootstrap also creates deployment, lookup, and asset-publishing identities.
Those are operator infrastructure, not application roles. The CloudFormation role receives
the project policy instead of AdministratorAccess. Runtime provisioning in P05 will require
a reviewed policy extension; do not attach an administrator policy to fix a failed deploy.

## Resource and retention inventory

| Resource | P04 configuration | Removal behavior / ongoing cost |
|---|---|---|
| `incident-demo-toolkit` | Project qualifier `incdemo`, termination protection | Retained bootstrap S3/ECR assets and IAM roles; shared by later project stacks |
| `incident-demo-cfn-execution` | Managed policy limited to foundation resources | IAM policy has no direct usage charge; remove only after bootstrap is no longer used |
| Artifact S3 bucket | Private, TLS-only, SSE-S3, ACLs disabled, versioned, access logging | RETAIN; `runs/` expires after 30 days, noncurrent versions after 7; `smoke/` after 1 day |
| Access-log S3 bucket | Private, TLS-only, SSE-S3, ACLs disabled | RETAIN; log expiry 7 days, incomplete uploads aborted after 1 |
| `incident-demo-state` | On-demand, 10 max read/write request units, pk/sk, AWS-owned encryption, 7-day PITR | RETAIN plus deletion protection; application writes `expires_at` TTL |
| `/incident-demo/foundation` | CloudWatch Logs with 7-day retention | RETAIN; logs continue to expire after stack deletion |

Both bucket names include the demo account and Ohio region. Stack termination protection
prevents accidental teardown. Retention protects evidence but is **not cleanup**: retained
objects, table data/backups and bootstrap assets can continue to cost money. No NAT gateway,
search cluster, model provisioned throughput, customer KMS key, or continuously running
compute is created by this baseline.

TTL is eventual cleanup, not approval expiry enforcement. PITR is recovery protection, not a
substitute for the atomic approval/action transaction. S3 lifecycle is not an immutable audit
guarantee. Export sanitized acceptance evidence before it expires. Access logging is enabled;
CloudTrail data events and scoped CloudWatch request metrics should be enabled and budgeted
with P05-P07 live access. Their absence in P04 is an explicit audit-coverage limitation.

## Spending limits and estimate

Bill approved **$50 total and $10 per batch** on October 5. Configuration reserves **$10 for
infrastructure**, leaving at most $40 for local model reservations. `budget.py` computes with
Decimal and rejects duplicate reservations, batch overruns and total overruns. A file lock
prevents competing local smoke processes from losing reservations. Failed or uncertain calls
keep their reservation; no automatic refund assumes that AWS did not bill them.

This ledger covers only tools that use it. It is not an AWS-wide hard spending limit, does
not include unrelated account activity, and is not a billing reconciliation system. P05 must
connect pre-call reservations, tokenizer/CountTokens input checks, retries, observed usage,
and concurrency limits to the live investigator. Do not expose a live batch path until that
enforcement is implemented. No email or SNS budget notification was configured.

| Model | USD per million input tokens | USD per million output tokens |
|---|---:|---:|
| Nova Lite | 0.06 | 0.24 |
| Nova Pro | 0.80 | 3.20 |
| Llama 3.3 70B | 0.72 | 0.72 |
| Titan Embeddings V2 | 0.02 | Not applicable |

The official Ohio price-list snapshot is [bedrock-prices.json](evidence/p04/bedrock-prices.json).
These are standard on-demand prices, not batch discounts or provisioned capacity.
[Bedrock pricing](https://aws.amazon.com/bedrock/pricing/).

At 6,000 input and 1,500 output tokens per call, with retries included within six calls per
investigation: 108 base investigations cost at most $0.46656; 36 comparison investigations
$2.07360; 12 single-call judge reviews $0.06480. The script-computed **model-only planning
total is $2.60496**. This excludes development, embeddings, retrieval, Guardrails, AgentCore,
storage, logging, tax and network transfer. The proposed token caps need quality checks in
P05; increasing them requires recomputing reservations rather than silently widening limits.

Foundation unit prices retained alongside this document: S3 standard $0.023/GB-month,
$0.005/1,000 PUT/LIST and $0.0004/1,000 GET; DynamoDB paid storage $0.25/GB-month plus
$0.20/GB-month PITR, $0.625/million write units and $0.125/million read units; CloudWatch
standard ingestion $0.50/GB and storage $0.03/GB-month. Free tiers are not assumed in the
planning allowance. Usage drives cost; the retention settings do not cap total volume.
[S3 pricing](https://aws.amazon.com/s3/pricing/),
[DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/),
[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/).

The planned P05-P07 resources are inventoried below; they are not provisioned by P04.
Their official Ohio catalog snapshots are the `*-future-prices.json` files in
[the evidence directory](evidence/p04/). Rates must be rechecked when live adapters are added.

| Planned resource | Charge basis in the retained snapshot | Budget treatment |
|---|---|---|
| AgentCore microVM runtime | v1: $0.0895/vCPU-hour and $0.00945/GB-hour; v2: $0.1276/vCPU-hour and $0.0169/GB-hour | Select compute version in P05; include initialization, system overhead and session memory |
| ECR container storage | $0.10/GB-month for standard storage | Keep only required image versions; no EC2 runtime selected |
| S3 Vectors | $0.06/GB-month storage; $0.20/GB ingested; query request, processed-byte and returned-byte charges | Eight small runbooks; bound ingested size, query count and metadata; no fixed-capacity search cluster |
| Bedrock Guardrails | Content and denied-topic policies each $0.00015/text unit; paid sensitive-information policy $0.00010/text unit | P06 freezes filters and bounds aggregate characters across all three boundaries; costs can exceed inference |
| ARM Lambda diagnostic/workflow functions | $0.0000002/request plus $0.0000133334/GB-second at first tier | Bound memory, duration, reserved concurrency and retry totals |
| Standard Step Functions workflow | $0.000025/state transition before free tier | Bound transitions/retries; callback waits do not justify unbounded orchestration |
| EventBridge custom events | $0.000001/64-KB chunk | Bound event payload and dispatch retries |
| Separate application IAM roles | No directly metered identity charge | Least privilege and denial tests remain P05-P07 |

[AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/),
[ECR pricing](https://aws.amazon.com/ecr/pricing/),
[Lambda pricing](https://aws.amazon.com/lambda/pricing/),
[Step Functions pricing](https://aws.amazon.com/step-functions/pricing/),
[EventBridge pricing](https://aws.amazon.com/eventbridge/pricing/).

The $2.60496 model-only estimate is **not** a full-stack experiment estimate. Before a live
investigation batch, calculate its retrieval, per-filter Guardrail units, runtime/session,
workflow and logging allowance too; split batches as needed to stay under $10. Development
and verification attempts count against the $50 total. A higher-cost runtime or continuously
billed store is not an automatic fallback. Price retrieval does not establish the final bill:
reconcile actual billing, pending reservations and retained storage before each later batch.
