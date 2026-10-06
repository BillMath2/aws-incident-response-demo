# P05 live investigator: deployment and operation

Target: account `498084841421`, profile `incident-demo`, Ohio (`us-east-2`). P05 reuses
the P03 LangGraph controller and adds actual LangChain/Bedrock calls, three diagnostic
Lambdas, and an IAM-authenticated AgentCore HTTP runtime. Diagnostics remain synthetic.
No approval, execution, retrieval, or Bedrock Guardrails endpoint is supplied by P05.

## Build and deploy

Use the existing Python 3.12.12, uv 0.9.5 and Node 22.17.0 environment. From the repo root:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
$env:JSII_RUNTIME_PACKAGE_CACHE_ROOT = Join-Path $PWD '.tools/jsii'
.\.tools\uv.exe sync --locked --extra live
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/package_live.py
Push-Location infra
.\.venv\Scripts\python.exe prepare_live_policy.py
.\.venv\Scripts\python.exe manage.py diff --live
.\.venv\Scripts\python.exe manage.py deploy --live
Pop-Location
```

`boto3[crt]` includes the dependency needed for the AWS CLI login credential provider.
No static access keys are written. The live optional dependencies and ARM64 wheels are
pinned in the root lockfile. NumPy 2.2.6 supplies the manylinux2014 ARM64 wheel required
by this package; CDK's own dependencies remain in their separate lockfile.

The packaging script exports locked hashes, installs ARM64 binaries into a versioned
local build directory, and writes a deterministic ZIP with Linux file permissions.
It includes source, versioned prompts and synthetic observations from development cases
only. It excludes evaluator labels, answer keys, held-out fixtures and runbooks. The
case-to-opaque-telemetry mapping stays in the local build manifest; it is not model input.
Code assets are content-addressed and uploaded to the project CDK bootstrap bucket.

This uses AWS's [direct Python deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html),
not a Docker build. The runtime implements `GET /ping` and `POST /invocations` on port 8080.
AgentCore performs IAM authentication before forwarding requests. PUBLIC network mode is
for this synthetic development workload; it does not mean anonymous invocation is allowed.

`prepare_live_policy.py` validates both generated policies with IAM Access Analyzer. It creates
or reuses `incident-demo-p05-cfn-execution` and `incident-demo-p05-monitoring-execution`;
an update is allowed only when the existing
document matches the previously retained project policy. Previous documents are retained
locally; at IAM's five-version limit, only an exactly archived non-default version is pruned.
The policies are attached to the project's CloudFormation role alongside the P04 policy.
Runtime creation also authorizes creation of its default endpoint and workload identity.
Those creation actions require the `Project=incident-demo` request tag and Ohio; runtime
tagging during creation requires the same project tag. Other runtime operations use
the project runtime ARN prefix. IAM administration/pass-role is limited to four P05 roles.
The first AgentCore deployment also creates its AWS-managed runtime identity service-linked
role. The deployment permission permits `iam:CreateServiceLinkedRole` only for that exact
account role and `runtime-identity.bedrock-agentcore.amazonaws.com` service name.
[AWS service-linked role requirements](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/service-linked-roles.html).

Review the diff before every deployment. Live-stack deployments preserve successfully created
resources on failure (`--no-rollback`) so a narrowly corrected retry can recover them.
They still use ordinary CloudFormation, not hotswap. Inspect stack events and CloudTrail before
adjusting permissions. The foundation is a separate stack and is not replaced by P05.

## Invoke a bounded development smoke

Use a new evidence directory every time. The first command initializes the cloud ledger only
if its global item does not exist; it never resets counters:

```powershell
.\.venv\Scripts\python.exe scripts/live_smoke.py --case case-001 --batch p05-dev-01 --initialize-budget --output runs/new-p05-baseline
.\.venv\Scripts\python.exe scripts/live_smoke.py --case case-005 --batch p05-dev-01 --output runs/new-p05-transient
.\.venv\Scripts\python.exe scripts/live_smoke.py --case case-001 --batch p05-dev-01 --model-calls 1 --output runs/new-p05-model-cap
.\.venv\Scripts\python.exe scripts/live_smoke.py --case case-001 --batch p05-dev-01 --deadline 0.1 --output runs/new-p05-deadline
.\.venv\Scripts\python.exe scripts/live_smoke.py --probe --batch p05-dev-01 --output runs/new-p05-permissions
.\.venv\Scripts\python.exe scripts/collect_live_evidence.py --output runs/new-p05-inventory
```

The CLI preserves requests, responses, transport IDs, failures and session-stop errors.
It stops the AgentCore session in a `finally` block. If stopping fails, the service idle
limit is 60 seconds and maximum microVM lifetime is 180 seconds.
[Lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html).

Each request has a run ID, batch ID, validated incident, opaque telemetry ID, variant and
bounded settings. Maximum HTTP input is 16 KiB; output is limited to 192 KiB. Private S3 run
records use `runs/p05/<run-id>.json` and conditional creation, so a repeated key is not overwritten.
The runtime worker has at most 120 seconds. The parent forcibly kills and reaps it on expiry;
it retains partial audit and marks usage unknown rather than fabricating a zero-cost result.
SDK connect/read timeouts further constrain calls. No SDK retry is hidden from the graph;
the graph permits at most one transient retry within six model and eight tool attempts.
The final adapter uses LangChain's native Bedrock Converse tool calls, with `toolChoice=any`.
It validates every proposed call against the original strict contracts. If Nova suggests
multiple calls, only the first validated decision reaches the sequential controller; the
others are logged as unused and are neither executed nor queued. More than four suggestions,
unknown tools, invalid arguments and non-tool responses fail closed. Model text and reasoning
blocks are ignored and never copied into traces.
[Nova tool choice](https://docs.aws.amazon.com/nova/latest/userguide/tool-choice.html).

The adapter exposes only response tools valid for the current graph phase. It expands schema
references inline and limits the top-level tool schema to Nova's supported fields; Pydantic
still enforces the complete original contract after generation. Once all three immutable
diagnostic snapshots are collected, it exposes only the finish response tool. Guidance is
versioned as `p05-v7-native`; each call logs system-prompt and tool-schema hashes. The frozen
P03 prompt files remain unchanged; P08 must freeze this adapter guidance as part of its
complete experiment configuration too.

The CLI transport timeout is 150 seconds, allowing time around the worker for reservation
and evidence persistence. A stopped client does not imply cancellation of a billed model call.
Uncertain requests keep their entire reservation. P07 must integrate this contract into its
Lambda bridge and persist workflow state separately.

## Budget behavior and token-count limitation

The approved project allowance remains $50 total, $10 per batch. The local P04 ledger reserves
$10 for infrastructure and retains its $0.10 smoke reservation. P05 adds an atomic cloud ledger
with a $39.90 ceiling and a $10 ceiling for each batch. A transaction reserves all of the run's
allowance, acquires one global investigation lease, and rejects an already-used run ID.
Reservations are never automatically refunded. A failed worker releases its lease but keeps
its money reservation; a crashed runtime's lease expires after 240 seconds.
P05's standalone provider/diagnostic preflights were reserved locally before their calls,
then reconciled into the cloud global and batch counters with a conditional transaction and
a unique marker. Both ledgers now account for the same $4.60 P05 reservation; the local ledger
also includes P04's $0.10. Future standalone calls must reserve their allowance and reconcile
it before another batch; never reset or decrement counters to make room.

Nova Lite v1 rejected `CountTokens` during live preflight. The wrapper still attempts exact
counting and rejects counts above 6,000 where supported. Only the specific unsupported-model
response for the two pinned Nova v1 models permits the alternate gate: **32 KiB of serialized
text input**, at most **1,500 output tokens**, and conservative reservation against the model's
entire **300,000-token context**. If reported input usage exceeds the 6,000-token planning target,
the run stops before another call. There is **no claim of an exact pre-call 6,000-token cap**
on these models. Other counting failures fail closed.

At the retained P04 prices, six calls at the full context and output bounds cost at most
$0.11016 in Nova Lite inference, or $1.4688 in Nova Pro inference. P05 therefore reserves
**$0.25 per Lite run** or **$2 per Pro run**, including a margin for its short compute, tools
and audit writes. The smoke CLI selects Lite. No retrieval or Guardrail charge is included
because those services are not called. P06 must recompute the allowance before enabling them.
[Nova model limits](https://docs.aws.amazon.com/nova/latest/userguide/what-is-nova.html),
[token-count API](https://docs.aws.amazon.com/bedrock/latest/userguide/count-tokens.html).

These are conservative reservations, not final AWS charges or an account-wide spending cap.
Avoid independent console/API invocations outside the runner. Reconcile the local ledger,
cloud counters and delayed AWS billing before later batches. Never delete budget items or
switch batch IDs to evade a limit. AWS administrators can bypass application controls.

## Security and audit boundaries

The three diagnostic functions have separate roles that can write only their own log streams.
They read immutable packaged observations, validate arguments and results, and perform no AWS
business-state mutation. The investigator can call the selected geographic Bedrock profiles,
invoke only those three functions, update its isolated budget table, write its P05 evidence
prefix, read its exact code asset and write its runtime logs. It has no foundation state-table
access, IAM management, Step Functions callback, approval or executor permission.

The runtime trust policy requires the demo account and the project runtime ARN prefix.
Lambda roles use the documented Lambda execution principal and scoped deployment pass-role
permissions. No function URL, API Gateway or public bucket is created. Inference profiles can
route through Virginia, Ohio and Oregon; stored evidence remains in Ohio.

CloudWatch logs use a customer-managed KMS key with rotation and seven-day retention. The
project CloudTrail logs management events plus project Lambda and AgentCore data events to a
private S3 bucket, with log-file validation and seven-day expiry. Structured application events
record run IDs, AWS request IDs, tool attempts, latency and actual token usage. Raw model prompts,
invalid responses and private reasoning are not copied into application traces. These are
structured logs and graph traces, not a claim of ADOT distributed tracing or AgentCore Evaluations.

Metric filters cover both DEFAULT and smoke runtime log groups. Two CloudWatch alarms track
failed runs and worker latency above 110 seconds. They expose alarm state without sending
notifications; no SNS recipient is configured. Custom metrics and alarms can incur charges.

The P05 boundary hook checks only synthetic canaries. It is explicitly labelled as such in every
response. A schema-valid response is not a semantic quality verdict. P06 must add real retrieval
and input/source/output Guardrails before the filtered-investigator milestone can be green.

## Retention and cleanup

Leave P05 deployed for P06. Runtime sessions stop automatically; no provisioned compute or
search cluster runs continuously. The retained log key costs $1/month, prorated hourly, plus
usage. Trail storage, code assets, logs, and the budget table also have usage/storage charges.
The first management-event trail copy is free; selected data events and S3 delivery/storage
are metered. [KMS pricing](https://aws.amazon.com/kms/pricing/),
[CloudTrail pricing](https://aws.amazon.com/cloudtrail/pricing/).

For final authorized cleanup, inventory both stacks and export evidence first. Stop active
sessions and the project trail before teardown. Disable termination protection only for the
intended stack. Retained budget table, trail bucket, log groups, KMS key and code assets require
separate reviewed cleanup; do not delete the key while retained encrypted logs are needed.
Follow the [P04 cleanup runbook](p04-deployment-runbook.md#cleanup-and-retained-charges) for the
foundation and bootstrap. No deletion is part of P05 acceptance.
