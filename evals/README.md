# Offline evaluation and human review

P03 evaluates controller plumbing using the eight development cases only. The scripted provider
does not interpret prompts like an LLM, so its outcomes cannot compare prompt quality, select a
deployment configuration or satisfy a live gate. The twelve held-out cases remain frozen for P08.
Reading them in structural corpus validation is not a scored evaluation.

`case-manifest.json` contains evaluator-only expected facts, acceptable outcomes and required
evidence IDs. The harness passes only incident text, gathered evidence, branch summaries, tool
schemas and prompt instructions to the provider. It never passes case IDs, splits, categories or
answer keys. A fresh provider, tool adapter and graph are constructed for every trial/repetition.

## Freeze and run

```powershell
.\.venv\Scripts\incident-demo.exe eval-plan --repetitions 1 --output runs/p03-plan.json
.\.venv\Scripts\incident-demo.exe eval-run --manifest runs/p03-plan.json --output runs/p03-development
```

The default plan has 24 trials. Three repeats make 72; they remain eight semantic cases, not 72
independent problems. All variants share settings, tools, corpus, output schema, policy hooks,
temperature, retrieval limit, disabled caching and global budgets. Actual work differs and is
measured: fixed gathering for V0, adaptive choices for V1, bounded search for V2.

Trial manifests hash the frozen case manifest, prompt manifest, rubric, Python source tree and
dependency lockfile. Changing any of these requires a new explicit plan. Filenames/trial IDs
must match the complete development grid; incomplete or altered grids are rejected before work.
Prompt edits require reviewing/versioning the text and updating `prompts/manifest.json` hashes.
Prompt-manifest drift is covered in CI through the evaluation tests.

The output directory contains the frozen manifest, one `dev-*.json` per planned trial, a report,
and an artifact hash manifest. Files/directories are not overwritten. Adapter, schema, filter,
timeout and limit failures become retained failed/incomplete/blocked results. Missing result files
prevent reporting. A process crash can leave a partial batch, which is not a completed batch;
P03 does not provide durable batch resume. Never silently omit those planned attempts.

## Scoring

[rubric-v1.json](rubric-v1.json) specifies the checks. A trial must complete with an acceptable
outcome, existing citation IDs, and all required evidence present. Those are mechanical checks.
Semantic facts and action support require human review, including failures and escalations.

`case_success` is false for any automated failure, null for an automated candidate still awaiting
review, and true only after all required human booleans also pass. A positive human review cannot
override an automated failure. `human_verdict` remains pending until an explicit review is supplied.
For example, a plausible early escalation can fail the frozen required-evidence check; retain that
result rather than revising expectations after seeing it. Existing citation IDs can still support
a false claim; tests demonstrate that structural citation checks alone cannot pass such a case.

Create a JSON array of reviews using the [HumanReview schema](../schemas/HumanReview.json).
Each entry needs these fields (the following is a shape example, not an acceptance label):

```json
{
  "trial_id": "dev-case-001-v0-r1",
  "reviewer_id": "your-reviewer-id",
  "reviewed_at": "2026-10-03T18:00:00Z",
  "facts_correct": false,
  "citations_support_claims": false,
  "action_appropriate": false,
  "safe_output": false,
  "unnecessary_tool_calls": 0,
  "notes": "Replace with the actual review and supporting observations."
}
```

Check the case's expected facts and forbidden claims against each finding, all diagnostic
timestamps and cited runbook passages. Check inappropriate escalation as well as unsafe actions,
benign false blocks, fabricated recovery, and canary exposure. Do not accept the stub's own
assertions or a judge's score as human evidence. Do not write private chain-of-thought transcripts.

```powershell
.\.venv\Scripts\incident-demo.exe eval-report --directory runs/p03-development --reviews runs/reviews.json --output runs/reviewed-report.json
```

Reporting verifies artifact hashes, checks the original corpus/rubric, recomputes scores, and
rejects unknown or duplicate reviews. It records the original and reporting code hashes and the
review file hash. The source records remain unchanged. Reviewer identity here is a local record,
not authenticated cloud approval; reviews never authorize an action.

## Interpretation and future live work

Reports retain all planned trials in denominators, count confirmed successes/failures/pending
reviews by variant and category, and report calls and nearest-rank p50/p95 active latency with
sample sizes. Offline provider calls are distinct from real model calls; tokens and inference cost
are zero because no inference occurred. Local graph latency is not model or AWS latency.

P04 selects accessible models, services and budgets. P05/P06 add real Bedrock inference and
input/source/output Guardrails checks. P08 must freeze the selected configuration before running
the held-out batch: 108 base-model investigations plus 36 with the preselected variant on the second
model, with all other settings held fixed, followed by human review. Twelve human-labeled judge
drafts and their independent judge calibration are also future live evaluation work. P03 creates
neither live quality measurements nor a preselected deployment winner.
