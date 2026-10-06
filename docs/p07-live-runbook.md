# P07 durable workflow runbook

Target: account `498084841421`, profile `incident-demo`, Ohio (`us-east-2`).
The approved allowance remains $50 total, $10 per batch, with $10 reserved for infrastructure.

## Flow and authority

Signed CLI → HTTP API with AWS_IAM → atomic intake/outbox → EventBridge custom bus
(`eventsv2`) → idempotent starter → Step Functions Standard → AgentCore bridge →
validated proposal → callback wait → isolated executor → independent synthetic health probe.

Analyst, approver and control-test roles use temporary STS credentials. The API verifies
the role in API Gateway's IAM context; body fields cannot supply identity or privileges.
These roles currently trust the owner's `managed/AccountFullAccessRole`. They demonstrate distinct
effective permissions, not separate human identities or separation from the account administrator.
Production would bind them to separately governed identities.

The approver reads the immutable investigation through the authenticated review endpoint,
checks factual support and citations, and submits its exact proposal hash, decision and reason.
Both review acknowledgments are required. They record a person's attestation; they do not
automatically prove that the investigation is factually correct. P08 owns quality review.

Each run has an isolated synthetic `checkout-api` service record. The only supported action
is `release-42` → `release-41`. No actual deployment, shell command or production service
is changed. The executor resolves all arguments from the stored, hashed proposal.

One DynamoDB transaction checks the proposal version, consumes the matching approval,
conditionally changes the service record and writes the receipt. A lost response or repeat
invocation returns the existing receipt. The subsequent observer reads the service separately
and writes an immutable health artifact. Failed or missing verification ends unresolved;
earlier investigation evidence and the receipt remain intact.

## Callback tokens, logs and retention

Tokens exist only in the private approval table and AWS's private workflow task input/history.
They are removed from the approval document on finalization and are never returned by the API,
put in URLs or exported in acceptance reports. Human
roles cannot read the approval table or workflow history and cannot call `SendTaskSuccess`.
The decision Lambda and callback recovery Lambda alone have callback permission; AWS requires
`Resource: *` for this API. Lambda code never logs incoming events. Workflow logs exclude
execution data. API integration Lambdas log request ID, trusted actor, route and HTTP status.
API Gateway access logs are disabled: automatic approval review rejected adding persistent
account-level log-delivery permissions. Detailed API metrics remain enabled. Requests rejected
by Gateway before reaching Lambda have aggregate metrics and retained client-side test evidence,
but no per-request server access-log record. This is an explicit demo observability limitation.

Approval expiration is 15 minutes, checked by application code at decision and execution.
The dedicated `control-expiry` scenario uses 30 seconds to exercise the same checks.
DynamoDB TTL is deliberately disabled: request identities, decisions and receipts remain
reserved indefinitely in these small retained tables. Operators must not delete/recycle them
to replay an old idempotency key. Use a new key for a new incident. S3 run artifacts retain
the foundation's 30-day lifecycle; CloudWatch logs retain seven days. Tables use point-in-time
recovery and deletion protection; the stack has termination protection.

## Recovery and bounds

Intake atomically writes request identity, run, outbox and isolated service state. Same role,
key and payload returns the same run; changed payload rejects. A bounded P07 batch counter
permits at most 32 accepted runs and three live investigations. This counter and the existing
runtime budget ledger survive process restarts; changing the allowance requires a reviewed
configuration/code change. The model runtime also enforces its existing batch/global monetary
limits, one-worker lease, six model calls, eight tools and 120-second deadline.

The one-minute dispatcher leases a pending outbox before each publish, with at most three
attempts. It retains pending status until the starter acknowledges `StartExecution`. A stable
execution name and immutable intake ID absorb duplicate events and lost publish responses.
Exhaustion writes a durable dead-letter status and sends a small run reference to SQS.
Subscriber delivery retries once, then uses the same DLQ. Inspect the failure and use a new
intake key after fixing it; do not reset counters or blindly replay dead letters.

Decisions persist before callback delivery. The one-minute callback recovery job retries
pending delivery and closes expired authority. A callback response alone never authorizes
execution. The executor rechecks the stored decision, actor, service, expiry and proposal hash.
Workflow task timeouts close approval authority; a timeout after a committed action becomes
unresolved until separately reviewed. Terminal records cannot be reopened by late callbacks.

The bridge caps runtime responses at 192 KiB, stores full evidence in private S3 and returns
only run/proposal state to Step Functions. An invocation claim prevents blind billed retries;
retries can read an already persisted runtime artifact. It requests runtime-session cancellation
on exit. Unknown outcomes fail closed and retain reservations/evidence for investigation.

## Commands

From the repository root with the existing pinned Python and AWS login:

```powershell
.venv/Scripts/python.exe scripts/package_workflow.py
infra/.venv/Scripts/python.exe infra/manage.py diff --workflow
infra/.venv/Scripts/python.exe infra/manage.py deploy --workflow
.venv/Scripts/python.exe scripts/p07_workflow.py start --scenario investigate --key my-incident-1
.venv/Scripts/python.exe scripts/p07_workflow.py status --run-id <run-id>
.venv/Scripts/python.exe scripts/p07_workflow.py review --run-id <run-id>
.venv/Scripts/python.exe scripts/p07_workflow.py decide --run-id <run-id> `
  --proposal-hash <reviewed-hash> --decision approved --reason 'Reviewed evidence and scope' `
  --facts-reviewed --citations-reviewed
```

`start` reserves $0.75 locally before a live intake; the runtime reserves the same amount in
the cloud ledger. The controlled acceptance harness reserves $0.75 once for its bounded batch,
in addition to the protected infrastructure allowance. Reservations are not measured billing
and are never automatically refunded. The two standing recovery schedules, logs, tables,
alarms, bus retention and KMS key incur continuing small charges until explicitly retired.

The `smoke --output <new-directory>` command exercises labeled controlled proposals with zero
model calls. Its automated signed approvals test the protocol, not independent human review.
Controlled proposals are never a fallback for an invalid or incomplete live model result.

`scripts/verify_p07.py` reads deployment controls and creates one controlled approval wait to
test actual callback denial under each user role. It holds the valid task token only in memory,
then rejects that probe through the signed endpoint. Invalid tokens cannot establish IAM denial
because Step Functions validates them first. `scripts/p07_delivery_check.py` matches the event ID
returned by publish against `failedMessages[].eventId` in the DLQ record; it exports the record
before removing only that test message. Other dead letters are retained for operator review.

The verified October 6 package and results are indexed in [P07 acceptance](p07-acceptance.md).
The Python SDK client name is `eventbridgev2`; `eventsv2` is the service's IAM prefix.

## AWS references and deployment notes

- [HTTP API IAM authorization](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-access-control-iam.html).
- [Step Functions callback integration](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html).
- [Custom EventBridge bus IAM namespace](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-custom-bus-names.html).
- [Subscriber delivery and DLQ](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-custom-bus-subscribers.html).
- [API Gateway management condition keys](https://docs.aws.amazon.com/service-authorization/latest/reference/list_apigatewayv2.html).

CDK's bundled regional schema initially reported EventsV2 types unavailable. Live Ohio
CloudFormation `DescribeType` returned `FULLY_MUTABLE` for both resources on October 6, 2026;
only that specific stale-schema warning is acknowledged. CloudFormation early validation
remains active. The P07 deployment policy adds no KMS permissions; API mutations are pinned
to API `ko8n1lkhkc`, and other mutations use the P07 resource name scope. API Gateway demanded
the literal `apigateway:TagResource` permission on stage creation while Access Analyzer marked
it unknown. That exact finding is retained as an explicit exception; its permission is scoped
to this API's stage collection and stages. All other findings remain fatal to installation.
