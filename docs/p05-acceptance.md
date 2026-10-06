# P05 acceptance: live investigator and diagnostic tools

Target: account `498084841421`, profile `incident-demo`, Ohio (`us-east-2`).
Verification date: October 5, 2026 (some AWS timestamps are October 6 UTC).
**P05 is complete for the live integration and bounded-control scope.** P06 is next.

P05 adds the live LangChain Bedrock adapter to the existing bounded LangGraph controller,
an IAM-authenticated AgentCore Python runtime, and three separately scoped diagnostic
Lambda functions. The AWS compute and model calls are real; diagnostic observations are
frozen synthetic development fixtures. The package contains no held-out fixtures or answer keys.
See the [live deployment and operating runbook](p05-live-runbook.md).

## Live acceptance

| Gate | Observed result | Evidence |
|---|---|---|
| Runtime deployment | AgentCore runtime and `smoke` endpoint READY on version 5; stack UPDATE_COMPLETE | [Runtime](evidence/p05/inventory/runtime.json), [endpoint](evidence/p05/inventory/endpoint.json), [deployed template](evidence/p05/live-template.json) |
| End-to-end investigation | Nova Lite selected all three scoped Lambda diagnostics, then returned a cited escalation; 4 model / 3 tool calls; worker 9,877 ms | [Final baseline](evidence/p05/p05-baseline-5/response.json) |
| Transient tool failure | Synthetic transient log fault occurred inside the real Lambda; exactly one retry, then completion; 4 model / 4 tool calls | [Retry trace](evidence/p05/p05-transient-1/response.json) |
| Model-call cap | One model call and one tool call, then `model_budget_exhausted`; retained partial evidence | [Call-limit result](evidence/p05/p05-model-cap-1/response.json) |
| Hard worker deadline | 0.1-second deadline forcibly stopped the worker in 101 ms; result incomplete, usage explicitly uncertain | [Deadline result](evidence/p05/p05-deadline-1/response.json) |
| Runtime IAM boundary | Real investigator-role calls denied foundation-state reads and executor dry-run invocation | [Permission probe](evidence/p05/p05-probe-1/response.json) |
| Endpoint authentication | Unsigned invocation rejected with HTTP 403 / AccessDeniedException | [Unsigned request](evidence/p05/unsigned-invocation.json) |
| Atomic reservations | Concurrent lease and duplicate-run transactions rejected; counters unchanged by both rejections | [DynamoDB checks](evidence/p05/budget-guards.json) |
| Private run evidence | All 9 runtime responses match their private S3 records, with AES256 encryption | [S3 readback](evidence/p05/artifact-readback.json) |
| Observability | Correlated runtime/Lambda logs; five encrypted seven-day log groups; key rotation enabled; real failure alarm transitions | [Inventory](evidence/p05/inventory/snapshot.json), [log groups](evidence/p05/inventory/log-groups.json), [alarm history](evidence/p05/inventory/failure-alarm-history.json) |
| Audit delivery | Project CloudTrail is logging and has delivered AgentCore/Lambda data events to private S3 | [Trail status](evidence/p05/inventory/trail-status.json), [delivered events](evidence/p05/inventory/trail-data-events.json) |
| Replay and drift | Zero differences, repeat deploy `(no changes)`, drift DETECTION_COMPLETE / IN_SYNC / zero drifted resources | [Diff](evidence/p05/p05-repeat-diff.log), [replay](evidence/p05/p05-repeat-deploy.log), [drift](evidence/p05/drift.json) |

The deadline bounds the worker, not cold-start/network time; that request took 2,985 ms
end to end. Every live smoke session was stopped by the caller. CloudTrail delivery is
asynchronous; the immediate final-run traces are in CloudWatch and the matching S3 records.
The [final CloudTrail snapshot](evidence/p05/trail-final.json) correlates all four final
invocations by their transport request IDs. The earlier snapshot is retained to show delivery lag.
All **23 retained acceptance/readback checks passed**:
[check results](evidence/p05/acceptance-checks.json). The
[SHA-256 manifest](evidence/p05/manifest.json) identifies source, package and evidence files.

## Local verification

- Application tests: **145 passed** with the live optional dependencies installed.
- Infrastructure tests: **15 passed**, including the explicit cdk-nag AWS Solutions scan.
- Ruff lint and formatting passed. CI installs the live extra but makes no AWS calls.
- Direct AWS preflight returned valid evidence from all three diagnostic functions:
  [retained observations](evidence/p05/direct-diagnostic-preflight.json).
- IAM Access Analyzer returned no findings for the two generated deployment policies.

Hosted P05 CI has not been observed. Local checks and synthetic development smoke calls
do not establish model quality, held-out performance, or a clean-account rebuild.

## Deployment corrections

CloudFormation's first AgentCore creation checks permissions against `runtime/*` before a
named runtime exists. Creation also requires permission for its implicit default endpoint,
workload identity and project tagging. The final creation statements constrain request tags
to `Project=incident-demo` and the region to Ohio where applicable. Named-resource operations
remain scoped to the project. The first deployment also required the AWS-managed runtime
identity service-linked role; only that exact role/service can be created by this permission.

AWS rejected the original ZIP entrypoint `python main.py`; the artifact now uses the documented
`["main.py"]` entrypoint. Dependency wheels target ARM64/Python 3.12. The ZIP is also used by
the diagnostics and fits Lambda's stricter uncompressed-size limit.

The account's concurrency quota is ten, all of which AWS requires to remain unreserved.
P05 therefore uses an atomic global DynamoDB lease for one investigation at a time instead
of Lambda reserved concurrency. It does not modify the account quota or organization policies.

Deployment uses ordinary CloudFormation with successful resources preserved after failure.
Failed attempts and prior policy documents are retained. When IAM's five-version limit is
reached, the installer removes only a non-default version whose exact document has already
been archived locally. The original P04 execution policy remains unchanged.

The four initial live investigations produced three strict-validation failures and one
budget-limited repeated-tool loop. Nova added Markdown fences, mixed response fields, or
repeatedly requested immutable logs. All attempts are retained. The final adapter uses
native Bedrock tool calls through LangChain, presents only relevant response tools, expands
schema references inline, and requests a finish after all three available snapshots are
collected. Every suggested call is validated, and only the first reaches the sequential
controller; additional suggestions are recorded as unused. This guidance is versioned
`p05-v7-native`; every call records system-prompt and tool-schema hashes. The original P03
prompts remain frozen. Six separately reserved provider-format checks and two local native-tool
preflights are labelled as diagnostics, not AgentCore acceptance or quality evaluation.

One schema-valid development response incorrectly described freshness/corroboration as
missing despite the supplied observations. It remains in
[format diagnostic 6](evidence/p05/format-diagnostic-6.json). P05 verifies integration and
mechanical controls; semantic review and model-quality gates remain outstanding for P08.

## Cost controls and scope limits

The user-approved allowance remains **$50 total / $10 per batch**, including the existing
$10 infrastructure reserve. Lite runs reserve $0.25 before execution; failures and unknown
usage retain their full reservation. The cloud ledger rejects duplicate run IDs, overlapping
leases and exhausted batches atomically. These controls are not an account-wide billing cap.
The conservative full-context reservations will not fund the original P08 model matrix from
the remaining allowance without reconciliation or revised planning. Revisit that budget before
starting P08; this package does not authorize increasing the allowance.

P05 retains **$4.60 in conservative reservations**; including P04, the local total is **$4.70**,
with the separate **$10 infrastructure reserve** still protected. The cloud ledger also
records **$4.60** after a monotonic, idempotency-protected reconciliation of the existing
local-only preflight reservations. No reservation was refunded or counted twice in the project
total. [Reconciliation evidence](evidence/p05/budget-reconciliation.json).
Across retained P05 calls, AWS reported 31 model calls, 62,132 input tokens and
4,792 output tokens. At the retained P04 rates, that reported inference is estimated at
**$0.004878**, excluding other services and uncertain usage. It is not a measured AWS bill.
[Usage and reservation accounting](evidence/p05/cost-and-usage.json).

Nova Lite/Pro v1 reject CountTokens. P05 enforces a 32 KiB serialized text-input limit and
1,500 output tokens, reserves against all 300,000 context tokens, and stops future calls if
reported input exceeds the 6,000-token planning target. It does **not** claim an exact pre-call
6,000-token limit. See [preflight](evidence/p05/token-count-preflight.json) and the runbook.

Retrieval and real Bedrock Guardrails remain P06 work. The runtime explicitly labels its
synthetic-canary check and unavailable retrieval. It can investigate and escalate but cannot
approve or execute a rollback. P07 owns the durable approval/action workflow. Structured
CloudWatch events are retained; this is not an ADOT distributed-tracing implementation.

The stack remains deployed for P06. KMS, logs, metrics/alarms, trail storage, code assets and
DynamoDB can incur retained charges; cleanup steps and limitations are in the runbook.
