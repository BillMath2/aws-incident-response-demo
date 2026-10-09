# P10 cleanup plan — prepared, not executed

Account **498084841421**, region **us-east-2**, profile **incident-demo**. The exact initial
resource scope is in the [stack inventory](evidence/p10/initial-stack-inventory.json): five
stacks, 147 stack-managed resources, plus [separately inventoried policies and logs](evidence/p10/initial-additional-inventory.json).
Refresh that scope after recording. No termination or deletion protection has been disabled.

The initial archive `.tools/p10/aws-snapshot-02/` contains five sanitized tables and 92 current
run artifacts. Its 106 files were hash-verified. It does not preserve all historical S3 versions,
CloudTrail files or CloudWatch events. Decide which of those must survive and export them before
the final, exact deletion review. Keep the release source, video and needed evidence outside the
resources being deleted. The local saved-evidence interface can continue to work after AWS cleanup.

## Dependency order after the recording is accepted

1. Recheck account/region and resource identities. Confirm no pending investigation, approval,
   active runtime lease or ingestion job. Finish/reconcile unknown outcomes; never reset counters.
2. Stop further intake and the two project recovery schedules after all work is terminal.
   Export final artifacts, receipts and verification. Preserve needed audit evidence before stopping
   the project trail. This is final retirement, not a change to the running demo's security controls.
3. Retire `incident-demo-workflow`: API, workflow, subscriber and worker functions. Its retained
   custom bus, queue, three tables, logs and KMS key require separate treatment.
4. Retire `incident-demo-live`: runtime/endpoint, diagnostics and project trail. Its budget table,
   trail bucket, logs and KMS key remain under their retention policies.
5. Retire `incident-demo-retrieval`: explicitly remove the data source/KB, then the vector index
   and vector bucket, and the Guardrail versions/Guardrail. Data-source deletion alone does not
   remove retained vectors. Verify dedicated role dependencies before deleting roles.
6. Retire `incident-demo-foundation` only after downstream use ends. Separately handle retained
   artifact/access-log buckets, the state table and foundation log group. Bucket emptying must
   account for object versions and delete markers, not just visible current objects.
7. Retire `incident-demo-toolkit` last, after deployment dependencies end. Inventory its assets,
   ECR images, roles, parameter and attached project deployment policies first. Do not delete
   unrelated service-linked roles or the owner's account role.
8. Verify every intended deletion with the owning service API. Reconcile retained backups,
   replaced resources, untagged leftovers, keys pending deletion and object versions separately.
   A successful CloudFormation delete is not sufficient evidence of zero retained resources.

This document is a reviewable sequence, not an executable bulk-delete script. Before destructive
execution, present the refreshed exact resource list and retention choices to the owner. Recording
completion and evidence preservation must precede that final deletion decision.

## Retained resources and potential continuing charges

| Resources in scope | Remaining usage/storage to reconcile |
|---|---|
| Four S3 buckets, including bootstrap assets | Current objects, historical versions, access/audit logs and requests |
| Five DynamoDB tables | Data storage, reads/writes, PITR or retained backups |
| Two customer-managed KMS keys | Key retention and requests; preserve decryptability until encrypted evidence is exported |
| Nineteen stack-managed log groups and four alarms | Stored logs, ingestion, metrics and alarms; stopping invocations alone does not remove them |
| S3 Vectors bucket/index and Knowledge Base | Stored vectors and any ongoing ingestion/query operations |
| Custom event bus, DLQ and recovery schedules | Event retention/delivery, queue requests and scheduled Lambda operations |
| Toolkit ECR repository | Retained images/storage, even if the runtime uses ZIP deployment |
| Runtime, model calls and Guardrails | Future invocations/checks until callers are retired |

These are inventory categories, not a measured bill or monthly estimate. No new commitments or
pricing assumptions were introduced. After cleanup, inspect delayed billing and list the exact
resources retained, with their charge basis. The approved $250 allowance and application reservations
are not an account-wide spending cap.

CloudFormation `Retain` explicitly leaves resources in place after stack deletion, with applicable
charges continuing. [AWS DeletionPolicy documentation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html).
Termination protection must be changed only on intended project stacks during authorized retirement.
[AWS termination-protection documentation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-protect-stacks.html).
