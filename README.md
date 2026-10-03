# AWS incident response demo

A synthetic checkout incident-response demonstration being built with Python, LangGraph,
LangChain and Amazon Bedrock AgentCore. **P01 is implemented and locally verified:** contracts,
runbooks, a frozen case corpus and offline checks. Investigation, approval and sandbox execution
start in P02. No live AWS behavior or model-quality results are claimed yet.

The [master implementation plan](docs/aws-incident-response-demo-master-implementation-plan.md)
defines scope. [P01 acceptance evidence and review notes](docs/p01-acceptance.md) record the current
state and remaining limitations.

## Setup

Use uv **0.9.5** and Python **3.12.12**. The Python version is in `.python-version`; direct
dependencies and the build backend are pinned in `pyproject.toml`, with transitive versions
and artifact hashes in `uv.lock`. P01 needs no AWS account, credentials or environment variables.
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

## Repository contents

| Location | Purpose |
|---|---|
| `src/incident_demo/contracts/` | Strict Pydantic tool and record contracts |
| `src/incident_demo/corpus.py` | Separate fixture, knowledge and evaluator loaders |
| `schemas/` | Generated JSON Schemas; CI checks for drift |
| `fixtures/cases/` | Synthetic incident inputs and ordered tool responses; no answer keys |
| `knowledge/` | Eight versioned runbooks, including stale and conflicting passages |
| `evals/case-manifest.json` | Evaluator-only split, expectations, acceptable outcomes and hashes |
| `tests/` | Offline contract and corpus integrity checks |
| `.github/workflows/ci.yml` | Lint, format, unit, corpus and schema checks |

Future runtime adapters and infrastructure will be added with their work packages. LangGraph,
LangChain and AWS dependencies are deferred until they have an implemented consumer and can be
verified against the selected AWS runtime.

## Contract boundaries

Tool calls allow only three read-only diagnostics and runbook retrieval for `checkout-api`.
The sole future action is a sandbox record transition from `release-42` to `release-41`.
The investigator tool union excludes execution and approval. Executor input contains stored
proposal and approval references, never client-supplied action arguments.

Records reject unknown fields, coercible string/boolean counts, unsupported targets, naive
timestamps, invalid digests and oversized evidence. Evidence payloads and proposals use SHA-256
over sorted, compact UTF-8 JSON; timestamps normalize to UTC. `Proposal.create(...)` constructs
the hash, and normal validation verifies it on reloading. Keep untrusted input on the validation
path: Pydantic `model_construct` and unvalidated `model_copy(update=...)` are not input parsers.

The record schema does not establish identity, authorize a person, consume an approval, check
wall-clock freshness or perform a transaction. Those controls require P02/P07 orchestration.
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
Runbook freshness and conflict resolution are application responsibilities in later packages.

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
