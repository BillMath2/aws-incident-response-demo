# P03 acceptance: prompt variants and evaluation harness

Date: October 3, 2026. Status: implemented; local acceptance checks passed.
Bill reported P02 green in GitHub. P03's hosted workflow has not been observed in this session.
This package proves offline control flow and evaluation plumbing, not live model quality.

## Implementation evidence

| P03 requirement | Retained evidence |
|---|---|
| V0 structured decomposition | Versioned prompt; fixed health/change/log/runbook gathering, followed by a single structured provider response |
| V1 ReAct | Versioned prompt and executable tool/observation loop; provider chooses each next tool or finishes based on gathered evidence |
| V2 bounded hypothesis search | Versioned prompt; seed at most two causes, perform at most two discriminating check/update rounds, track support/contradiction references, prune, and select or escalate |
| Shared constraints | Same tool/output contracts, corpus, boundary policy, temperature, cache policy and global call/deadline limits in each frozen trial plan |
| Bounded search tests | Reject extra candidates, duplicate/changed identities, invented references, resurrection of pruned branches, extra rounds, unsupported selections and tied action selections |
| Scoring rubric | Versioned automatic and human criteria; mechanical matches cannot count as case success without semantic review |
| Trial manifests | Hashes of source, lockfile, corpus, prompts and rubric; full development grid, independent resets and explicit settings |
| Fault behavior | Count retries in total budgets; retain failures/caps/blocks; fail closed on invalid schema, unavailable filtering and deadline exhaustion |

The implementation uses actual LangGraph 1.2.12 `StateGraph` execution, pinned with its transitive
dependencies in `uv.lock`. The investigation graph has gather, provider and tool nodes connected
by conditional edges. Local state is per invocation; no durable checkpointing is claimed.
The API was checked against the [official graph documentation](https://docs.langchain.com/oss/python/langgraph/graph-api)
and the [pinned package release](https://pypi.org/project/langgraph/1.2.12/).

`OfflineProvider` returns scripted structured decisions to exercise those graphs. V1's decisions
are adaptive to observations but are still scripted. V2 maintains competing causes across checks;
it does not generate three finished drafts. Its ranking is the count of distinct supporting IDs
minus contradicting IDs, with explicit pruning rules. That structural ranking is not semantic
proof or a probability. Ties cannot select an action. Human claim-support review remains required.

## Local validation

```text
uv sync --locked --offline                      PASS
uv run --locked --offline ruff check .           PASS
uv run --locked --offline ruff format --check .   PASS
uv run --locked --offline pytest                 134 passed
uv run --locked --offline incident-demo validate-corpus
  Offline corpus valid: {'development': 8, 'held_out': 12, 'runbooks': 8}
uv run --locked --offline incident-demo schemas --check
  Schemas verified.
```

The 51 new tests cover graph paths, search state transitions, call/retry/deadline bounds,
invalid/oversized outputs, privileged tool attempts, fabricated citations, mechanical proposal
preconditions, filter failures, canary output, manifest drift, missing trials, human-review scoring,
artifact tampering and isolated trial state. The existing 83 P01/P02 tests also pass.
Engine tests forbid socket connections and enable the LangSmith environment flag to verify that
the graph's explicit tracing suppression keeps the offline path offline.

## Retained batch and fault traces

[Trial manifest](evidence/p03/development/manifest.json) freezes one repetition of each variant
on eight development cases: **24 planned and retained investigations**.
[Report](evidence/p03/development/report.json) and
[artifact hashes](evidence/p03/development/artifacts.json) accompany every individual result.

| Variant | Trials | Scripted provider calls | Diagnostic/retrieval calls | Automated failures | Success candidates pending review |
|---|---:|---:|---:|---:|---:|
| V0 | 8 | 8 | 33 | 0 | 8 |
| V1 | 8 | 37 | 30 | 1 | 7 |
| V2 | 8 | 31 | 33 | 0 | 8 |

Actual model calls, model tokens and inference cost are zero. **All 24 human reviews are pending**
and there are zero confirmed case successes. This table cannot select a winning strategy.

The V1 dependency case escalates after its first health observation. Its outcome matches, but it
does not collect all evidence required by the frozen case. That trial remains an automated failure
in the denominator. The expected case was not weakened to improve the reported result.

[Fault traces](evidence/p03/faults.json) separately retain model-retry exhaustion, tool-budget
exhaustion, unavailable filtering and a late provider response. They are explicit offline fault
injections, not extra scored semantic cases. Each produces a terminal incomplete/failed result
without an action. The final batch and faults have no approval/execution integration.

An early development smoke run caught the simple canary filter blocking benign runbook text that
mentions the bare `DEMO_CANARY_` prefix. The check now requires a value after the prefix, and the
benign security-language development case has a regression test. The early smoke files remain
under ignored `runs/p03-smoke/`; they are not silently substituted into the retained final batch.
This was a development correction, not held-out tuning.

## How to review or reproduce

```powershell
.\.venv\Scripts\incident-demo.exe eval-plan --output runs/new-p03-plan.json
.\.venv\Scripts\incident-demo.exe eval-run --manifest runs/new-p03-plan.json --output runs/new-p03-batch
.\.venv\Scripts\incident-demo.exe eval-report --directory docs/evidence/p03/development --output runs/p03-review-report.json
```

Use new paths; existing results are preserved. The report can accept an explicit JSON array of
human reviews using `--reviews`. [Evaluation instructions](../evals/README.md) explain the rubric,
review schema and interpretation. No human-pass labels were fabricated for the retained batch.

## Boundaries and next package

- P01's frozen incident corpus, split, expected answers and runbooks remain unchanged. Only
  development cases were executed. Expected facts, case IDs and evaluator labels never enter the
  provider request. Structural integrity checks still inspect all frozen files.
- Six provider invocations, eight tool/retrieval calls, one transient retry per operation and a
  120-second deadline are initial bounds. Scripted invocations are recorded separately from actual
  model calls. Failed attempts consume budget. All trials count, including those blocked or capped.
- The deadline is cooperative: checks run before and after operations and the remaining timeout
  is passed to adapters. P05 must enforce real transport timeouts/cancellation; a synchronous
  adapter that ignores its timeout cannot be forcibly interrupted by this local controller.
- Input, source and output policy hooks fail closed, but their offline implementation is only a
  synthetic-canary check. Bedrock Guardrails coverage, regional support and false-positive quality
  remain P06 work. No arbitrary source instructions grant privileges or execute commands.
- Prompts request concise evidence summaries and decisions, not private chain-of-thought. Unknown
  reasoning fields fail schema validation. Public traces retain validated actions and branch states,
  not raw invalid provider responses or error payloads.
- No cost estimate, model-size comparison, deployment selection, held-out scoring, judge calibration
  or release-gate result has been manufactured. Those need the actual AWS adapters and P08 review.
- P02's local approval/action demo stays separate. P05 can adapt investigation results to the
  shared contracts; P07 must prove authenticated cloud control and durable action guarantees.

P04 is next: account/region/model readiness, supported feature checks, IAM and resource/cost
inventory, an agreed live-work budget and the CDK foundation. No AWS resources were deployed by P03.
