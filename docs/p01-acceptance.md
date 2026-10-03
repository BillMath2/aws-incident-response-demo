# P01 acceptance and implementation review

Date: October 3, 2026. Status: P01 implemented; local acceptance checks passed.
Hosted CI has been configured but has not been run or observed in this session.

| P01 gate | Retained implementation/evidence |
|---|---|
| Reproducible local environment | Python 3.12.12, uv 0.9.5, pinned `pyproject.toml`, hashed `uv.lock`; fresh `.tools/p01-replay` environment created with `uv sync --locked --offline` from the populated cache |
| Shared typed contracts | Tool argument/result contracts plus request, run, evidence, investigation, proposal, approval, executor input, action receipt and evaluation records; generated `schemas/` |
| Versioned runbooks | Eight Markdown documents with passage/document IDs, versions, owners, validity intervals, status and content hashes in `knowledge/catalog.json` |
| Versioned fixtures and declared split | Twenty cases: eight development, twelve held-out; expectations and hashes frozen separately in `evals/case-manifest.json` |
| Lint/unit CI | Windows/Linux GitHub Actions workflow; local Ruff lint/format, pytest, schema and corpus checks pass |

Local validation commands (with workspace-local uv and cache configured as in README):

```text
uv sync --locked --offline                     PASS (fresh cached replay environment)
uv run --locked --offline ruff check .          PASS
uv run --locked --offline ruff format --check .  PASS
uv run --locked --offline pytest                39 passed
uv run --locked --offline incident-demo validate-corpus
  Offline corpus valid: {'development': 8, 'held_out': 12, 'runbooks': 8}
uv run --locked --offline incident-demo schemas --check
  Schemas verified.
```

Tests exercise invalid JSON; unsupported targets, tools and mutation requests; unknown privilege
fields; bounded queries/results; evidence tampering and immutability; timezone validation;
invented references; canonical proposal hashes and tampering; executor input separation;
receipt transition invariants; manifest/fixture/runbook drift; and evaluator metadata exclusion.
They explicitly demonstrate that an existing citation can still support a false statement.
These are P01 structural checks, not completion of W02-W08 workflow or AWS gates.

The held-out composition matches the plan: four actionable cases; three dependency,
missing-evidence or conflicting-evidence cases; three instruction/exfiltration attempts;
and two stale-data or persistent-failure cases. Benign security terminology occurs in both splits.
No prompts have been tuned and no scored model evaluation has been run. The source-spoofing
case uses a redacted synthetic canary placeholder; active canary leakage testing and malicious
retrieved-source variants remain P03/P06 work.

Review decisions:

- P01 follows the master plan's package numbering. P02 owns the stub investigator, in-memory
  state, approve/reject CLI flow, synthetic action and exported run records.
- Use the standard-library CLI, Pydantic, pytest and Ruff now. Add and pin LangGraph/LangChain/CDK
  when their implementation packages need them; no unused framework or cloud scaffolding is claimed.
- Evidence is inline and bounded to 32 KiB. Validated private artifact references belong to the
  live bridge implementation. Local clocks derive from fixture incident time.
- Six model calls, eight tool calls, one retry and a 120-second deadline remain proposed investigation
  bounds; P03 will enforce and record them. P01 fixture generation makes no model calls.
- The plan links to a job description, two comparisons and two earlier plans that are absent from
  this checkout. Their contents and the plan's historical service comparisons were not independently
  reviewed in P01. Recheck time-sensitive AWS capabilities and pricing in P04.

No AWS resources were deployed. No credentials were needed or read. The generated fixtures and
runbooks are synthetic. A local green run does not prove authorization, distributed atomicity,
effective IAM, filtering quality or incident-resolution quality. P02 is the next work package.
