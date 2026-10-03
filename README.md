# AWS incident response demo

A synthetic checkout incident-response demonstration being built with Python, LangGraph,
LangChain and Amazon Bedrock AgentCore. **P01-P03 are implemented and locally verified:**
contracts, a frozen case corpus, a local approval walkthrough, and executable LangGraph
investigation variants with an offline evaluation harness. No live AWS behavior or model-quality
results are claimed yet.

The [master implementation plan](docs/aws-incident-response-demo-master-implementation-plan.md)
defines scope. See [P01 acceptance](docs/p01-acceptance.md) and
[P02 acceptance and retained walkthroughs](docs/p02-acceptance.md), and
[P03 acceptance](docs/p03-acceptance.md).

## Setup

Use uv **0.9.5** and Python **3.12.12**. The Python version is in `.python-version`; direct
dependencies and the build backend are pinned in `pyproject.toml`, with transitive versions
and artifact hashes in `uv.lock`. Local mode needs no AWS account, credentials or environment variables.
It does not read `.env`.

With [uv installed](https://docs.astral.sh/uv/getting-started/installation/), run from the repository:

```sh
uv sync --locked
uv run --locked incident-demo validate-corpus
uv run --locked incident-demo schemas --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

On this Windows workspace, uv and Python have been installed locally under ignored `.tools/`.
Use these equivalent PowerShell commands without changing system PATH:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.tools/python'
$uv = '.\.tools\uv.exe'
& $uv sync --locked
& $uv run --locked incident-demo validate-corpus
& $uv run --locked incident-demo schemas --check
& $uv run --locked ruff check .
& $uv run --locked ruff format --check .
& $uv run --locked pytest
```

The first setup downloads Python and packages. Subsequent commands can use `--offline` after
the cache is populated. `--locked` fails if dependency declarations no longer match the lockfile.
GitHub Actions runs the checks on Windows and Linux, without AWS secrets or paid calls.
See [uv's CI guidance](https://docs.astral.sh/uv/guides/integration/github/) and
[locking behavior](https://docs.astral.sh/uv/concepts/projects/sync/).

## Local walkthrough (P02)

From this Windows workspace, start interactive review:

```powershell
.\.venv\Scripts\incident-demo.exe demo --case case-001
```

Or, with uv on PATH: `uv run --locked incident-demo demo --case case-001`.
The CLI prints facts, citations, the exact proposal, its expiry and SHA-256 hash.
Enter `approve` or `reject`, then paste that hash. Enter `pending` (or close input) to
export an unapproved proposal. No input is never interpreted as consent.

For a scripted **simulated** decision and independent health observation:

```powershell
.\.venv\Scripts\incident-demo.exe demo --case case-001 --decision approve
.\.venv\Scripts\incident-demo.exe demo --case case-001 --decision reject
.\.venv\Scripts\incident-demo.exe demo --case case-001 --decision approve --verification unhealthy
.\.venv\Scripts\incident-demo.exe demo --case case-004 --decision pending
.\.venv\Scripts\incident-demo.exe demo --case case-005 --decision approve
```

Each invocation starts a new in-memory sandbox at release-42, revision 0. The stub gathers
health, changes, logs and fixture runbook passages. It retries a transient diagnostic at most once.
Case 001 demonstrates a deployment regression; 002 a dependency outage; 003 incomplete evidence;
004 injected source instructions; and 005 a transient failure followed by a successful retry.
Cases 006-008 cover stale evidence, conflicting guidance, and benign security language.
Only these eight development cases are available in the walkthrough CLI.

The narrow stub recognizes a serializer regression pattern; other diagnoses require escalation.
It is not a general incident classifier, model experiment, or robust injection detector.
The original fixture corpus and evaluation manifest are unchanged. Held-out cases have not been
used to tune this implementation or scored against it.

Approval is bound to the displayed proposal hash, allowed service, release and 15-minute expiry.
The local executor checks that binding again, consumes approval, changes the sandbox record,
and records a receipt under one process lock. Repeated matching commands return the same receipt.
Approval and execution roles are separate **simulated identities**, not real authentication or
an isolation boundary against someone who controls the Python process. `--actor local-investigator`
demonstrates that the investigator identity cannot approve.

A separate synthetic health observer runs after the receipt. `--verification recovered`,
`unhealthy`, or `missing` selects that observer's fixture, not the action result. Healthy, fresh
post-action data is required for `resolved`; failed/missing verification is `unresolved`.
These labels describe the sandbox demonstration only. The scenario clock starts at the fixture
incident time and advances with elapsed time, including human waiting. Approval waiting is
reported separately from measured active processing time.

Exports go to `runs/<run-id>.json` by default. `--output <new-file.json>` selects a new destination;
existing files are refused. Records include source hashes, versions, tool attempts, evidence,
proposal, approval, action receipt, verification and audit events. A small scrubber removes known
`DEMO_CANARY_` values and terminal controls before public records; it is not a general secret filter.
Exports are review artifacts and cannot be loaded to resume a run or authorize an action. All local
state and idempotency memory disappear on process exit. Exit code 0 means the command completed;
inspect the exported run state for resolution, rejection, escalation or incompleteness. Control
rejections and observer failures return 2; setup/contract/export failures return 1.

## Offline prompt experiments (P03)

Run setup again to install the locked LangGraph dependency. Then freeze and execute a development
batch (8 cases x 3 variants x 1 repetition = 24 trials):

```powershell
.\.venv\Scripts\incident-demo.exe eval-plan --output runs/p03-plan.json
.\.venv\Scripts\incident-demo.exe eval-run --manifest runs/p03-plan.json --output runs/p03-development
.\.venv\Scripts\incident-demo.exe eval-report --directory runs/p03-development --output runs/p03-report.json
```

These commands require new output paths. `eval-plan --repetitions 3` creates 72 development trials.
The manifest pins settings, prompts, code, dependencies, rubric and corpus; execution rejects drift.
No held-out execution or live provider can be enabled through these commands.

| Variant | Executable control flow |
|---|---|
| V0 | Fixed health/change/log/runbook gathering, then one structured response |
| V1 | Provider selects a diagnostic or retrieval call, observes its result, then continues or finishes |
| V2 | Initial health/changes, at most two candidate causes and two check/update rounds; prune, select or escalate |

The same LangGraph controller enforces a maximum of six provider invocations, eight tool calls,
one retry per transient operation within those totals, and a 120-second cooperative deadline.
V2 keeps concise candidate states, evidence IDs, check choices and pruning decisions. It is not
three finished drafts. The scripted provider exercises these paths using development fixtures;
it is not an LLM and the controller's evidence-count ranking is not proof of claim support.

All variants use shared tool/output contracts and input/source/output boundary hooks. P03's
boundary implementation only checks synthetic canary values; it is not Bedrock Guardrails.
Remote LangSmith tracing is explicitly disabled for these offline graphs. There is no approval
or executor in the experiment harness; P02's `demo` command remains a separate walkthrough.

Every planned result, including failures, blocks and caps, is retained. `provider_calls` records
scripted invocations while actual model calls, tokens and inference cost stay zero. Automated
checks can fail a case, but a matching outcome cannot pass without human review of material facts,
semantic citation support, action appropriateness and output safety. Reports always mark the live
gate false. See [rubric and review workflow](evals/README.md) and
[retained P03 report](docs/evidence/p03/development/report.json).

## Repository contents

| Location | Purpose |
|---|---|
| `src/incident_demo/contracts/` | Strict Pydantic tool and record contracts |
| `src/incident_demo/corpus.py` | Separate fixture, knowledge and evaluator loaders |
| `src/incident_demo/investigator/` | Explicitly labeled deterministic local stub |
| `src/incident_demo/investigator/engine.py` | LangGraph V0/V1/V2 control flow and shared bounds |
| `src/incident_demo/evaluation/` | Frozen trial planning, execution, scoring and reporting |
| `prompts/` | Shared instructions, three versioned variants and a hashed manifest |
| `src/incident_demo/workflow/`, `storage/` | Local orchestration and in-memory state adapter |
| `src/incident_demo/local_tools.py` | Fixture diagnostics and independent synthetic verification |
| `schemas/` | Generated JSON Schemas; CI checks for drift |
| `fixtures/cases/` | Synthetic incident inputs and ordered tool responses; no answer keys |
| `fixtures/local-verification.json` | Separate P02 verification profiles; outside the frozen incident corpus |
| `knowledge/` | Eight versioned runbooks, including stale and conflicting passages |
| `evals/case-manifest.json` | Evaluator-only split, expectations, acceptable outcomes and hashes |
| `tests/` | Offline contract and corpus integrity checks |
| `.github/workflows/ci.yml` | Lint, format, unit, corpus and schema checks |

LangGraph 1.2.12 now runs the offline strategies; its dependencies are locked. The Bedrock
LangChain integration and live runtime adapters remain P05 work after P04 readiness decisions.

## Contract boundaries

Tool calls allow only three read-only diagnostics and runbook retrieval for `checkout-api`.
The sole action is a sandbox record transition from `release-42` to `release-41`.
The investigator tool union excludes execution and approval. Executor input contains stored
proposal and approval references, never client-supplied action arguments.

Records reject unknown fields, coercible string/boolean counts, unsupported targets, naive
timestamps, invalid digests and oversized evidence. Evidence payloads and proposals use SHA-256
over sorted, compact UTF-8 JSON; timestamps normalize to UTC. `Proposal.create(...)` constructs
the hash, and normal validation verifies it on reloading. Keep untrusted input on the validation
path: Pydantic `model_construct` and unvalidated `model_copy(update=...)` are not input parsers.

The record schema does not establish identity, authorize a person, consume an approval, check
wall-clock freshness or perform a transaction. P02 implements local control checks; cloud
authentication, durable atomicity and effective IAM enforcement remain P07 work.
An evidence `sanitized` flag records producer responsibility; it is not a filtering engine.
Citation validation checks existence, including retrieved passage IDs, and does not prove
semantic support. An action receipt records a synthetic mutation and cannot claim recovery.

## Corpus use and changes

The frozen v1 corpus contains eight development and twelve held-out semantic cases. Use only
the development split for prompt tuning. Structural validation of held-out files is allowed;
do not use their expected answers to implement investigator decision rules. The fixture loader
does not read `evals/`, and evaluation fields are rejected in fixture JSON. Future cloud packaging
must exclude `evals/`; directory separation alone is not an access-control boundary.

Fixture response order models diagnostics and, where present, a transient failure followed by
a usable retry. Timestamps are synthetic: use each incident's `submitted_at` as the local scenario
clock, not today's date. Retrieval passage IDs select fixture responses; they are not scoring labels.
The local stub checks runbook freshness and escalates on unresolved conflicts; live retrieval and
filtering remain later work packages.

The manifest pins every fixture and the knowledge catalog; the catalog pins Markdown content
and passage metadata. `evals/case-manifest.sha256` detects manifest drift. Git enforces LF line
endings so hashes match on Windows and Linux. This is a reviewable freeze, not a cryptographic
signature or a secret test set.

For an intentional corpus revision, preserve the previous evaluation evidence, review all changed
expectations and split assignments, update the corpus version and hashes, and document the reason.
Do not silently refresh hashes after tuning on held-out failures; create fresh held-out cases before
claiming another unbiased confirmation. Current schemas deliberately accept only corpus v1.

To regenerate schemas after a reviewed contract change:

```sh
uv run --locked incident-demo schemas
```

JSON Schema expresses structural constraints. Cross-field validators, hash checks, and Python
runtime tests remain necessary. All telemetry, identities, effects and runbook guidance here are
fictional demo data.
