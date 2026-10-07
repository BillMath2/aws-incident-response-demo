# P08 live evaluation runbook

P08 is in progress. The current executable stage is the development evaluation; the full
held-out matrix and judge calibration are not complete. Use the existing Ohio account
`498084841421` and `incident-demo` profile. On October 6, the owner approved $250 total and
retained $10 per batch, including a protected $10 infrastructure reserve. Prior reservations
remain charged against that ceiling. No infrastructure deployment is required to finish the
frozen development baseline. The runtime retains its stricter original cloud ceiling until a
reviewed update for subsequent stages; changing local configuration alone does not raise it.

## Frozen development plan

`scripts/p08_evaluate.py` freezes 24 development investigations: eight cases, V0/V1/V2,
one repetition, Nova Lite. It verifies the deployed diagnostic package against the local
opaque telemetry map and pins runtime version, artifact, environment, diagnostic hashes,
Knowledge Base and numbered Guardrail. The manifest also pins evaluator corpus/rubric,
prompts, source, lockfile, model configuration, price snapshot and runner source.

Only the incident, opaque telemetry ID, run ID, variant and bounded settings reach AgentCore.
The agent never receives evaluator case IDs, categories or expected answers. Each invocation
uses a unique session and requests cancellation afterward. These experiments invoke the
investigator directly; they do not invoke the P07 approval or execution path.

```powershell
.venv/Scripts/python.exe scripts/p08_evaluate.py budget
.venv/Scripts/python.exe scripts/p08_evaluate.py freeze-development --output runs/p08-plan.json
.venv/Scripts/python.exe scripts/p08_evaluate.py run --plan runs/p08-plan.json --directory runs/p08-development --max-trials 12
.venv/Scripts/python.exe scripts/p08_evaluate.py report --plan runs/p08-plan.json --directory runs/p08-development --output runs/p08-report.json
.venv/Scripts/python.exe scripts/p08_evaluate.py review-packet --plan runs/p08-plan.json --directory runs/p08-development --output runs/p08-review.json
```

The runner stops after one monetary batch (at most $10), even when `--max-trials` is larger.
Reservations are $0.75 per Lite investigation and $2.50 per Pro investigation. The local
ledger, cloud ledger and single-worker lease remain enforced; no reservations are refunded
automatically. The first P08 invocation is capped at 12 Lite trials / $9.

A local exclusive lock prevents overlapping runners. Each trial claims its identity before
reservation/invocation and writes its result with exclusive creation. Restarting after a
claim can recover an existing private S3 artifact, but cannot repeat the billed invocation.
Absent artifacts produce an `unknown` record and stop the batch. Transport, usage-accounting
or session-stop failures also stop the batch. Inspect a stale `.runner.lock` only after
confirming the prior process has exited; do not remove a lock to start concurrent work.

Saved results are immutable. Any source/configuration drift requires a new, explicitly named
plan, with earlier attempts retained. Do not regenerate a plan merely to rerun a poor result.

## Targeted development repairs

After an explicitly documented development change, `freeze-repair --variant V2` freezes all
eight development cases for that variant on Nova Lite ($6 in one batch). This is a diagnostic
repair run, not a replacement for the original 24-trial baseline or a model-selection result.
Its stage, source, deployment and run identities differ from the baseline. Use a new directory
and retain every failure. Other variants require their own explicit plan and reservation.

```powershell
.venv/Scripts/python.exe scripts/p08_evaluate.py freeze-repair --variant V2 --output runs/p08-repair-plan.json
.venv/Scripts/python.exe scripts/p08_evaluate.py run --plan runs/p08-repair-plan.json --directory runs/p08-repair --max-trials 8
```

The first repair preserves the frozen corpus, expected outcomes, conflict checks and proposal
preconditions. It restricts live search to uncollected sources, derives the search response tag
from the native tool name, clarifies factual/verification instructions, and adds validation-field
diagnostics without recording rejected values. Runbook conflict applicability remains unresolved;
do not filter away conflicting/stale passages merely to improve the score.

The second repair restores the scenario document inventories already frozen in the fixture
inputs. `scripts/package_live.py` writes an opaque-telemetry-ID-to-passage-ID map to
`retrieval-scopes.json`; the worker supplies that map to the retrieval adapter. It is not sent
to the model, and neither case categories nor expected answers determine the filter. Documents
still come from the real KB and retain all provenance, freshness and conflict validation.
Returned documents outside the inventory fail closed. If any inventory document is missing
(including when the model requests too few results), all returned guidance is marked incomplete.
The model cannot choose another inventory or certify completeness.

The filter combines service/corpus conditions with exact passage IDs using Bedrock's
[documented metadata filters](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_RetrievalFilter.html).
This tests retrieval and reasoning within a supplied synthetic document inventory; it is not
a benchmark of discovering document applicability in a production incident. The earlier unscoped
runs remain separate and failed; do not relabel them. The KB corpus and expected outcomes stay
unchanged, including the stale inventory in case 006 and conflicting inventory in case 007.

## Human review and interpretation

The fourth development repair adds at most one native schema/format correction per
investigation. It shares the existing per-step retry allowance and consumes the same six
model-call and 120-second limits. Only sanitized field locations and validator error types
are returned to the model; rejected response content is discarded. The model must supply
the corrected answer itself. No facts, candidate IDs or citations are inserted automatically.
Punctuation-only `next_check` strings are rejected; JSON null remains allowed. Repeated
malformation fails closed, and citation, candidate, Guardrail and proposal checks still apply.
Unknown tool names, unsafe transitions and policy failures are not repairable format errors.
Trace/audit records retain correction events and usage. This is a separately frozen protocol
revision; do not combine its results with previous revisions for a same-configuration comparison.

The fourth repair's live corrections did not fix punctuation-only follow-ups. A transport-level
regression test then found that pinned `langchain-aws==1.8.0` converts `bind_tools` definitions
through `_strip_null_anyof`, removing null branches even on required fields. Inspecting the
pre-conversion Pydantic schema was insufficient. The fifth repair binds native Bedrock
`toolConfig` directly through `ChatBedrockConverse`, preserving required nullable fields while
retaining the same counted client, parser, correction limits and boundary checks. The regression
test exercises actual LangChain transport down to a fake client's `converse` method, and live
audits hash the actual transmitted tool configuration. No SDK upgrade or contract relaxation
is involved. AWS documents the Nova tool schema subset in
[Defining a tool](https://docs.aws.amazon.com/nova/latest/userguide/tool-use-definition.html).

The review packet includes the exact saved result and expected facts, acceptable outcomes,
forbidden claims and required evidence. These files are evaluator-only and must not be copied
into an agent prompt or deployment package. Review every attempted investigation, including
failed/blocked results and escalations. Inappropriate escalation fails actionable cases.

For each entry, fill the `review_template` fields and collect those objects into a JSON array.
Leave nothing implicitly approved. `reviewer_id`, time, factual support, citation support,
action appropriateness, safe output, unnecessary tool count and explanatory notes are required.
The template includes the saved record's hash; a review of another revision is rejected.

```powershell
.venv/Scripts/python.exe scripts/p08_evaluate.py report --plan runs/p08-plan.json --directory runs/p08-development --reviews runs/p08-human-reviews.json --output runs/p08-reviewed-report.json
```

The report keeps all planned trials in its denominator, explicitly distinguishes `not_run`,
unknown transport and model outcomes, and never counts an unreviewed candidate as confirmed
success. It reports model/variant groups, case/category rows, known tokens/calls, inference
cost estimates, unknown usage and nearest-rank active p50/p95 with sample size. Inference
estimates are not total AWS charges; service usage remains in the original audit records.
Human waiting is excluded. This development report cannot satisfy the final release gate.

## Remaining stages

1. All 24 frozen development trials are recorded under the approved $250 total ceiling.
   Review the results and resolve development failures before selecting a variant; do not
   choose on one favorable run. See `development-complete-report.json` and
   `development-complete-review-packet.json` in `docs/evidence/p08/`.
2. Run and review the selected variant with Nova Pro on the agreed development cases.
3. Freeze a deployment candidate and rationale from development evidence. The library defines
   the 144-trial held-out grid, but the CLI intentionally does not expose held-out execution
   before the selection/review gate and held-out telemetry deployment are implemented.
4. Execute the unchanged 108 Lite + 36 Pro held-out trials if funded, and review every result.
   Do not tune on held-out outcomes or hide failures behind a new manifest.
5. Prepare 12 drafts (six supported, six flawed), obtain actual human labels, run the separate
   Llama judge, and report false accepts/rejects, agreement, cost and latency. Judge labels must
   never stand in for human labels or authorize an action.
6. Produce the complete quality/cost/latency report with all frozen gates and limitations.

The existing P06/P07 evidence documents a model-quality limitation: bounded, schema-valid
outputs can still have unsupported claims or inappropriate escalation. P08 measures that
behavior; it does not assume the deployed configuration is ready for release.
