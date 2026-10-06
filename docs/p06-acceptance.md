# P06 acceptance: Knowledge Base and explicit Guardrails

Target: account `498084841421`, profile `incident-demo`, Ohio (`us-east-2`).
Verification: October 5, 2026 local time / October 6 UTC.

**The P06 retrieval and boundary-control gates are verified. V2's model-quality result
is not green; its unsupported proposal was rejected, as detailed below.**

P06 adds real Bedrock retrieval over the frozen eight-document corpus in S3 Vectors,
plus numbered Guardrail checks at input, retrieved/tool source, and generated-output
boundaries. The workload remains synthetic; filtering and citation validation do not
establish factual correctness or grant permission to act. See the
[deployment and operating runbook](p06-live-runbook.md).

## Acceptance evidence

| Check | Observed result | Retained evidence |
|---|---|---|
| Ingestion | Eight documents and eight metadata files scanned; eight indexed, zero failures/skips | [Ingestion](evidence/p06/ingest-1/ingestion.json) |
| Corpus provenance | All eight actual retrieved passages match frozen S3 locations, metadata and text hashes | [Passage checks](evidence/p06/verify-1/passages.json), [upload manifest](evidence/p06/upload/manifest.json) |
| Freshness/conflict handling | Current, stale and conflicting metadata survives retrieval; normal rollback query returns those distinctions | [V0 trace](evidence/p06/live-v0-1/response.json) |
| Benign filtering | All eight runbooks and benign input/source/output samples allowed | [Boundary results](evidence/p06/verify-1/boundaries.json) |
| Attack filtering | Input/source prompt attacks blocked; synthetic-secret exposure blocked at all three boundaries | [Real API results](evidence/p06/verify-1/audit.json) |
| Fail closed | Six controller probes: interventions and unavailable-version API errors stop input/source/output; no canary retained in results | [Controller probes](evidence/p06/probes-1/controller-boundaries.json) |
| V0 live path | One model / four tool calls, ten Guardrail checks; cited escalation after conflicting guidance; worker 11,334 ms | [V0 response](evidence/p06/live-v0-1/response.json) |
| V1 live path | Five model / four tool calls; model selected retrieval and escalated on conflicting guidance; worker 10,080 ms | [V1 response](evidence/p06/live-v1-1/response.json) |
| Final-package replay | Runtime version 8 completed V0 with one model / four tool calls; worker 8,329 ms | [Final V0](evidence/p06/live-final-v0/response.json) |
| Live malicious input | Guardrail blocked before any model/tool call; worker 2,317 ms | [Runtime block](evidence/p06/live-input-attack-1/response.json) |
| IAM remains isolated | Actual business-state read and executor invocation denied after P06 permissions were added | [IAM probe](evidence/p06/live-iam-probe/response.json) |
| Deployment readback | Runtime version 8 READY; code hashes, S3 records, pinned configuration and ledgers match; 41 checks pass | [Final readback](evidence/p06/readback-final.json) |
| Drift and repeatability | Both stacks IN_SYNC; zero remaining live/retrieval CDK differences | [Live drift](evidence/p06/live-drift.json), [retrieval drift](evidence/p06/retrieval-drift.json), [live diff](evidence/p06/live-repeat-diff.txt), [retrieval diff](evidence/p06/retrieval-repeat-diff.txt) |
| Local application checks | 147 passed; includes metadata/text/location rejection, bounded/full-coverage filtering and native response schema | [Final test output](evidence/p06/application-tests-final.txt) |
| Infrastructure checks | 16 passed, including narrowed permissions, retained vector resources, pinned version and six valid audit selectors | [Infrastructure tests](evidence/p06/infrastructure-tests.txt) |

The controller fault harness uses real `ApplyGuardrail` calls with explicitly offline
model/tool doubles. Only the `live-*` runtime responses demonstrate the complete AWS
compute/model path. No held-out cases were run or used for tuning.

## Retained failures and protocol correction

The first V2 smoke stopped at `search_round_limit` after three model / four tool calls,
in 8,330 ms. The model requested another check after the second search round. Its native
schema still permitted that field, so the final-round schema was tightened to require
`next_check: null`, with matching protocol guidance. The controller limit itself was not
relaxed. The [failed response](evidence/p06/live-v2-1/response.json) and full reservation
are retained. This is a contract correction on development data, not a held-out quality result.

The [single follow-up](evidence/p06/live-v2-2/response.json) respected the search-round
limit, then attempted a rollback proposal without the full required evidence. The controller
rejected it with `missing_proposal_evidence` after four model / four tool calls, in 15,640 ms.
No action was possible or taken. V2 needs quality work before P08 acceptance; it is not
presented as a successful investigation. Both failed trials count in the retained cost ledger.

Local synthesis caught an invalid CloudTrail selector array before deployment; it was
corrected to six separately scoped selectors. An early infrastructure test invocation
hit a Windows shared-temp permission error; the suite passed with a workspace-local temp
directory. All deployed P06 resource creation succeeded on its first AWS attempt.

## Scope and remaining gates

Version 1 enables content, prompt-attack and synthetic-secret regex filtering. It does not
enable contextual grounding, real-PII filters, denied topics or Automated Reasoning.
Prompt-attack detection is input-only; source material is explicitly evaluated as INPUT.
Filtering decisions are recorded with full character coverage and service usage, without
raw assessed content or matched values. Service failures and incomplete coverage stop work.

The role can retrieve only this KB and apply only this Guardrail. Runtime code pins its
numbered version. Standalone application checks are not organization-wide enforcement.
The investigator still cannot approve or execute a business action. Durable event routing,
authenticated approval, action isolation and replay protection belong to P07; semantic
model quality and the frozen comparison belong to P08. The original $50/$10 approval
is unchanged, and the P08 matrix requires budget reconciliation before execution.

## Cost and reproducibility

P06 retained **$7.50** across ten $0.75 reservations in batch `p06-dev-01`, including both
failed V2 trials and the actual IAM-denial probe. The local ledger totals **$12.20** across
P04–P06. DynamoDB totals **$12.10**, with the P04-only $0.10 reservation accounted for
locally; the P06 batch counter is $7.50 and the lease is released. There is **$27.80** left
in the model/testing allowance plus the protected **$10** infrastructure reserve. These
are conservative reservations, not the AWS bill; none was refunded after failures.

The final ARM64 ZIP SHA-256 is
`20b89c876e4f68ac170b91085f4e44a4315e6ac8aa3b8981aadf57e0ed73c004`.
[Package metadata](evidence/p06/package-final-formatted.json) records its size and fixture
mapping. All three Lambda code hashes match, and the AgentCore runtime references the same
asset. The [SHA-256 manifest](evidence/p06/manifest.json) binds the final source and evidence.
Earlier package/deployment records remain to explain the schema correction and formatting update.

CloudTrail selectors cover this exact KB and Guardrail in addition to AgentCore and diagnostics.
The [final audit snapshot](evidence/p06/audit-final/trail-data-events.json) records delivered
events; delivery is asynchronous, so it is not an assertion that every recent request has
already arrived. Each live runtime response retains immediate AWS request IDs, including
retrieval and Guardrail calls, for correlation. Model invocation logging is disabled;
five runtime/diagnostic log groups remain private, KMS-encrypted and limited to seven days.
