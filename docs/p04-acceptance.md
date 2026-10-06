# P04 acceptance: AWS readiness and deployment foundation

Verified October 5, 2026 in account `498084841421`, profile `incident-demo`, region
`us-east-2` (Ohio). **P04 is complete for the foundation scope.** P05 is next; no live
incident investigator, retrieval index, Guardrail policy, or approval workflow is claimed.

Bill approved $50 total and $10 per batch, selected Ohio, and selected a standard Bedrock
Knowledge Base backed by customer-managed S3 Vectors for P06. The deployment required no
organization-policy change. See [readiness decisions](p04-aws-readiness.md) and the
[deployment and cleanup runbook](p04-deployment-runbook.md).

## Acceptance evidence

| Gate | Observed result | Retained evidence |
|---|---|---|
| Target and service readiness | Demo account verified; Ohio APIs readable; selected text/embedding models available and geographic inference profiles active | [Preflight](evidence/p04/preflight.json) |
| Real text-model access | Three fixed synthetic Converse requests succeeded, one per selected text model | [Model smoke](evidence/p04/model-smoke.json) |
| Scoped deployment permissions | Deployed policy v3 matches the generator; execution role has only that managed policy, no inline policies; Access Analyzer returned no findings | [Policy verification](evidence/p04/execution-policy-verification.json), [policy](evidence/p04/cfn-execution-policy.json) |
| Security validation | Explicit cdk-nag AWS Solutions scan succeeded with no unacknowledged violations | [Scan](evidence/p04/nag-report.json), [exact template](evidence/p04/foundation-template.json) |
| Deployment | Project toolkit and foundation reached `CREATE_COMPLETE`; both have termination protection | [Resource inventory](evidence/p04/deployment-inventory.json), [successful deployment log](evidence/p04/p04-deploy-retry.log) |
| Service readback | All 13 configuration checks passed, including private encrypted buckets, access logging, table caps/PITR/TTL/protection, and log retention | [Readback](evidence/p04/foundation-readback.json) |
| Repeatability | Follow-up diff reported zero differences; repeat deploy reported `(no changes)` | [Diff log](evidence/p04/p04-repeat-diff.log), [repeat deployment](evidence/p04/p04-repeat-deploy.log) |
| Drift | `DETECTION_COMPLETE`, `IN_SYNC`, zero drifted resources; all four drift-supported resources in sync | [Stack drift](evidence/p04/drift.json), [resource drift](evidence/p04/resource-drift.json) |
| Budget planning | Versioned limits and conservative reservation ledger; model-only experiment estimate $2.60496, with other service rates inventoried separately | [Configuration](../infra/config.json), [estimate](evidence/p04/budget-estimate.json), [cost inventory](p04-aws-readiness.md#spending-limits-and-estimate) |

The scan's sole documented acknowledgment is `AwsSolutions-S1` on the access-log destination
bucket, to avoid recursive access logging. The negative security test confirms an unprotected
bucket is detected. CDK's generic validation report alone is not the security-scan evidence;
the retained explicit `AwsSolutionsChecks` result is.

## Local verification

- Application suite: **134 passed**; corpus validation and schema checks passed.
- Infrastructure suite: **13 passed**, including target-account refusal, resource protections,
  a negative security scan, and reservation limits/concurrent-lock rejection.
- Application and infrastructure Ruff lint/format checks passed; `git diff --check` passed.
- CDK synthesis and its explicit security scan passed. Python and npm dependencies are locked
  separately under `infra`; the existing application lockfile was not changed.
- Offline Windows/Linux CI jobs are configured. A hosted CI run has **not** been observed.

The retained [SHA-256 manifest](evidence/p04/manifest.json) identifies the infrastructure
source, configuration, lockfiles and acceptance evidence. These results demonstrate deployment
and a no-op replay in this account, not a fresh-account rebuild; that remains a P10 gate.

## Attempts and corrections

The first bootstrap command hit Windows' `python` store alias before bootstrap provisioning.
The wrapper now passes the infrastructure environment's explicit Python executable for
bootstrap as well as ordinary CDK actions. Both [initial](evidence/p04/p04-bootstrap.log)
and [successful](evidence/p04/p04-bootstrap-retry.log) bootstrap logs are retained.

The first foundation deployment stopped before resource creation because the execution policy
lacked `ssm:GetParameters` on this project's bootstrap-version parameter. Policy v2 added
only that parameter read, after which deployment succeeded. The
[initial failure log](evidence/p04/p04-deploy.log) is retained.

The first drift check could not finish CloudFormation's log-group read handler because it
lacked `logs:DescribeIndexPolicies`. After checking the current resource schema, policy v3
added the required log read operations, scoped to the log group where supported and to Ohio
for the regional discovery calls. The [failed drift result](evidence/p04/drift-first-attempt.json)
and successful rerun are retained. No administrator policy was attached to resolve these errors.

The captured PowerShell logs include a `NativeCommandError` wrapper around CDK's informational
stderr line `AI agent detected`. That wrapper is not the native command's exit status.
Successful attempts exited zero and their results were independently verified with AWS APIs.

## Cost and remaining scope

The three smoke requests used 61 total tokens. Their combined **estimated inference charge
is $0.00004892** at the retained prices; this is not a measured total AWS bill. The full $0.10
smoke reservation remains in the private local ledger. Configuration reserves $10 for
infrastructure within the $50 total allowance. The local ledger is not an AWS-wide spending
cap, and future batches must reconcile storage, runtime and other charges too.

The foundation remains deployed: two private S3 buckets, the protected on-demand DynamoDB
table, one CloudWatch log group, and the project's CDK bootstrap resources. Retention and
cleanup instructions are in the runbook; destroying a stack alone will not delete retained
resources. No destructive cleanup was performed.

Text-model smoke proves basic access only. It does not establish tool-use quality, embedding
invocation, document ingestion/retrieval, filter coverage, runtime IAM isolation, or authorized
action execution. Those live acceptance gates belong to P05-P07. Geographic inference profiles
may process requests in Virginia, Ohio or Oregon; foundation storage is in Ohio.
