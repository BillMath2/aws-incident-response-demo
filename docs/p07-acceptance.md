# P07 acceptance — verified in Ohio

P07's workflow gate passed on October 6, 2026, in account `498084841421`, `us-east-2`.
The stack is `UPDATE_COMPLETE`, the final CDK diff has no changes, and CloudFormation drift
detection reports `IN_SYNC` with zero drifted resources. This verifies the workflow and
authorization controls; independent model-quality evaluation remains P08 work.

## Implemented

- IAM-authenticated HTTP intake, review and decision routes; separate analyst, approver and
  controlled-test roles with temporary credentials and server-derived identity.
- Atomic intake/outbox creation, bounded scheduled dispatch, a new EventBridge custom bus,
  duplicate-safe execution names and a retained dead-letter queue.
- Step Functions Standard investigation, server-only approval callback, conditional sandbox
  transaction, immutable receipt and separate synthetic health observation.
- Proposal hash, expiry, service, expected release and actor checks; retry/rejection/expiry
  reconciliation; terminal token retirement; no investigator execution or approval authority.
- Signed CLI, live control harness, DLQ test and deployment readback/permission verifier.

The existing AgentCore runtime, Knowledge Base and Guardrail remain the investigation path.
Controlled workflow proposals are explicitly labeled and use a separate authenticated route;
they cannot turn a failed live model result into an approved proposal.

## Evidence available

- Application checks: 168 tests passed, including 21 durable control/recovery tests.
- Infrastructure checks: 19 tests passed, including the final logging configuration.
- Ruff: all checks passed.
- Real investigator IAM probe: executor invocation and foundation state read both returned
  `AccessDeniedException` after the executor function existed.
  [Probe result](evidence/p07/investigator-denial/response.json).
- Project deployment policy and exact validation exception retained under `docs/evidence/p07/`.
- [45 live control checks](evidence/p07/controls-2/checks.json): signed approval and rejection,
  edited hash denial, stable duplicate intake, duplicate/conflicting decisions, duplicate events,
  executor retry without a second mutation, expiry and late-decision denial.
- Approved recovery ended `resolved`; failed independent health verification ended `unresolved`.
  Rejection and expiry left the service unchanged. The expiry case used scheduled dispatch.
- [33 deployment/permission checks](evidence/p07/readback-checks.json): four signed routes,
  eleven separate Lambda roles, private workflow logs, protected/encrypted tables, bounded
  delivery, matching deployed package and actual denial under all three user roles.
  Callback denial used a valid private token held only in memory; the probe was then rejected
  through the signed endpoint. Fabricated tokens fail validation before IAM evaluation.
- [Subscriber DLQ evidence](evidence/p07/delivery-dlq.json): a malformed test event exhausted
  one retry with `COMPUTE_EXECUTION_ERROR`. Its returned event ID matched the dead-letter record;
  only that exact message was removed after export.
- [Final readback](evidence/p07/final-state.json): seven hash-verified artifacts, dispatch records,
  five private Lambda API audit records and cloud budget counters.

## AWS deployment and limitations

The `incident-demo-workflow` stack in Ohio contains the three retained DynamoDB tables,
private KMS-encrypted log groups, eleven separate Lambda roles/functions, EventBridge bus
and subscriber, Standard state machine, schedules, DLQ, HTTP API routes and scoped user roles.
The API stage and final package are deployed successfully.

Automatic approval review rejected adding persistent account-level CloudWatch log-delivery
permissions to the deployment role. The final source instead uses private Lambda request
audits and detailed API metrics. Gateway access logs are disabled with an explicit CDK
exception. Pre-integration rejections have aggregate metrics and client test evidence, but
no per-request server access-log record. Actual private Lambda request audits were read back.

The first control attempt exposed an SDK client-name error, corrected to `eventbridgev2`
and covered by a test using the installed SDK contract. Its bounded outbox exhausted retries,
recorded a dead letter and left the sandbox unchanged; [failure evidence](evidence/p07/controls-1/failure.json)
is retained. A first DLQ lookup used a payload marker, but this service exports event IDs
instead of original payloads. The corrected check passed; earlier failure messages remain
in the retained queue and are not automatically replayed.

## Real investigation

Run `p07-b0b557f6f18bbcc84ef86015427806267464aefa` traversed signed intake, scheduled dispatch,
EventBridge, Step Functions and the existing AgentCore runtime. Nova Lite V1 made five model
calls and four diagnostic/retrieval calls, with complete usage reporting: 11,622 input and
458 output tokens. The runtime completed; the workflow ended **escalated** with no proposal,
approval or sandbox mutation. [Sanitized trace](evidence/p07/live-investigation.json).

The model cited conflicting rollback guidance and requested further verification. Its factual
claims have not received independent human quality review. Controlled approvals above are
explicitly labeled automated protocol tests, not approvals of this model output. P08 remains
unstarted, and no held-out quality gate is claimed.

## Budget and limits

P07 has retained $2.25 in reservations: $0.75 each for control tests, the live IAM probe and
the real investigation, below the $10 batch allowance. Total local reservations are $14.45,
leaving $25.55 of the model/testing allowance plus the separate $10 infrastructure reserve.
Cloud reservations are $14.35; the $0.10 difference is the earlier local P04 allowance.
Reservations are conservative allowances, not measured AWS charges. Standing infrastructure
continues to incur charges until explicitly retired.

See the [operating runbook](p07-live-runbook.md) for commands and recovery behavior.
