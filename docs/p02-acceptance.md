# P02 acceptance: thin local end-to-end slice

Date: October 3, 2026. Status: implemented; local acceptance checks passed.
M1 (the local contract/workflow demonstration) is now demonstrated. Hosted CI has not been
observed during this package; no live AWS gate is claimed.

The CLI gathers three diagnostic fixtures and selected runbook passages, runs a labeled
deterministic stub, displays a canonical proposal and hash, accepts approval/rejection,
conditionally updates an in-memory sandbox service, performs a separate health observation,
and exports a structured JSON run record. Interactive review requires the displayed hash;
scripted review is explicitly labeled as a simulated decision.

## Acceptance evidence

| P02 requirement | Implementation and evidence |
|---|---|
| CLI investigates with labeled stub | `incident-demo demo`; `investigator/stub.py`; fixed read-only diagnostics and fixture retrieval; zero model calls |
| Exact proposal review and decision | Canonical proposal printed before decision; local approver scope and hash checked; rejection preserves service state |
| Synthetic transition | Executor-only command references stored proposal and approval; expiry/current release rechecked; mutation, consumption and receipt recorded under a process lock |
| Independent verification | Separate `fixtures/local-verification.json`; fresh post-action health required; unhealthy, missing, stale and observer-error paths stay unresolved |
| In-memory adapter | `storage/memory.py`; local intake/action idempotency and duplicate/concurrent execution tests; no cross-process recovery claim |
| Exported evidence | `LocalRunRecord` schema, immutable prior observations, call attempts, hashes, decisions, receipts and audit events; refuse overwriting retained exports |
| Selected negative tests | Wrong actors, missing approval, edited proposal, wrong hash, expired decisions/actions, stale release, duplicate/conflicting decisions, repeated actions, missing diagnostics, bounded retries, failed verification and synthetic-canary redaction |

Local verification results:

```text
uv sync --locked --offline                       PASS
uv run --locked --offline ruff check .            PASS
uv run --locked --offline ruff format --check .    PASS
uv run --locked --offline pytest                  83 passed
uv run --locked --offline incident-demo validate-corpus
  Offline corpus valid: {'development': 8, 'held_out': 12, 'runbooks': 8}
uv run --locked --offline incident-demo schemas --check
  Schemas verified.
```

The existing Windows/Linux workflow runs the new unit and CLI subprocess tests through pytest.
The environment and dependencies remain unchanged from P01. No paid calls or credentials are used.

## Retained walkthroughs

These records were produced by the actual local CLI with scripted simulated decisions, not
handwritten outcomes. All incident times and observations are synthetic. File hashes and
invocation selections are retained in the [evidence manifest](evidence/p02/manifest.json).

| Story | Final state | Sandbox revision | Record |
|---|---|---|---|
| Approve regression, healthy subsequent observation | resolved | 1 | [Approved and verified](evidence/p02/approved-recovered.json) |
| Approve regression, unhealthy subsequent observation | unresolved | 1 | [Applied but unresolved](evidence/p02/approved-unresolved.json) |
| Reject regression proposal | rejected | 0 | [Rejected](evidence/p02/rejected.json) |
| Dependency outage | escalated | 0 | [Dependency outage](evidence/p02/dependency-outage.json) |
| Incomplete diagnostic evidence | incomplete | 0 | [Incomplete evidence](evidence/p02/incomplete-evidence.json) |
| Injected source instructions | escalated | 0 | [Injected source](evidence/p02/injected-source.json) |
| Transient diagnostic failure, then successful retry | resolved | 1 | [Transient retry](evidence/p02/transient-retry.json) |

Start interactive review from the repository with:

```powershell
.\.venv\Scripts\incident-demo.exe demo --case case-001
```

Use `--decision approve`, `reject`, or `pending` for a scripted simulation, and
`--verification unhealthy` or `missing` to demonstrate unresolved verification. The default
export destination is a unique file under ignored `runs/`; retained acceptance records above
were explicitly exported into `docs/evidence/p02/`. See README for the full walkthrough.

## Boundaries and review notes

- The stub intentionally recognizes only the known development serializer regression pattern.
  It uses observations and current policy metadata, not case IDs or expected outcomes. It does
  not read `evals/`; a test runs the entire CLI in a copy with no evaluation files. No held-out
  cases were used to implement decision rules or scored against the stub.
- Original incident fixtures, runbooks and the frozen case manifest are unchanged. Separate
  verification fixtures and new JSON Schemas are additive. Synthetic-canary scrubbing recomputes
  hashes for the sanitized evidence; the input fixture digest retains provenance without raw secrets.
- The local role table is a simulation, not authentication or an isolation boundary. An owner of
  the process can change memory or select a simulated identity. P07 must prove effective IAM,
  trusted actor derivation, durable conditional transactions and distributed recovery.
- Local idempotency lasts only for one process. The memory lock prevents concurrent effects in
  that process; it cannot prove atomicity across process crashes or machines. Exports are never
  reloaded as authority or used to resume approval. Pending exports do not create durable waits.
- Approval waiting follows the synthetic scenario clock plus actual elapsed time. Expiry is
  checked on decisions and execution. There is no background timeout scheduler in this slice.
- `run.usage.tool_calls` counts investigation attempts, including failed calls and fixture retrieval;
  the independent verification observation is recorded separately. Active latency sums local
  investigation/execution/verification method time and excludes human waiting and CLI/file I/O.
  These are plumbing measurements, not live service or model performance results.
- Injection text never becomes an executable tool or privilege grant. The stub and its small
  canary/terminal-control scrubber are not Bedrock Guardrails or a general security filter.
  Live input/source/output filtering and adversarial quality checks remain P06/P08 work.
- The first smoke run revealed coarse Windows clock timestamps could make a post-action
  observation equal to its receipt time. Using the high-resolution elapsed clock fixes that;
  strict ordering remains enforced and is covered by CLI and stale-observation tests.

## Next work and remaining estimate

P03 adds actual prompt variants, bounded investigation/search logic and the evaluation harness.
P04 readiness can begin independently now that M1 exists, including region/model selection,
IAM/resource inventory, a cost allowance and the CDK foundation. Neither has started in P02.

The remaining P03-P10 baseline is **39-58 focused engineering hours**, plus **10-15 hours
contingency** (49-73 total). Preserve that allowance: a fast local slice does not establish the
cost of AgentCore integration, AWS fault recovery or human evaluation. Re-estimate again after
P05, when the bounded live invocation has actual acceptance evidence.
