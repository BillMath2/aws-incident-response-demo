# P06 retrieval and Guardrails runbook

Target: `incident-demo` profile, account `498084841421`, `us-east-2`.
Use the existing $50 total / $10 batch approval; $10 stays reserved for infrastructure.
All diagnostic observations and runbooks are synthetic. The Bedrock, AgentCore, Lambda,
S3 Vectors and Guardrail API calls are real.

## Architecture and fixed choices

The `incident-demo-retrieval` CDK stack owns the vector bucket/index, Knowledge Base,
data source, KB service role and numbered Guardrail. The existing `incident-demo-live`
stack owns the investigator and its narrow retrieval/filter permissions.

- Knowledge Base: `XKVH8PLCHO`; data source: `CVMNH90331`.
- Vector bucket: `incident-demo-vectors-498084841421-us-east-2`; index: `runbooks-v1`.
- Embeddings: Ohio Titan Text Embeddings V2, 1,024 float dimensions, cosine distance.
- Source: the existing private artifact bucket, prefix `knowledge/p06-v1/`.
- Eight frozen Markdown documents, each one passage; chunking `NONE`. Replacing the
  chunking strategy requires a new data source. Original corpus files are unchanged.
- Guardrail: `a4aiug3xzh6e`, immutable version `1`. Content filters MEDIUM,
  prompt-attack filter HIGH on INPUT only, and a BLOCK regex for synthetic secret values.
- Source and vector encryption use SSE-S3. Runtime logs retain the existing customer
  KMS encryption, private access and seven-day retention. No new KMS key is needed.

The application calls `Retrieve` and then its existing Converse adapter. It does not
use `RetrieveAndGenerate`, which would own answer generation, or a separate manual
vector search implementation. This keeps all three investigation variants on the same
schemas, model-call accounting, citation checks and filtering path.

Guardrail integration alternatives are whole-request `guardrailConfig`, selective
`guardContent` blocks in Converse, and standalone `ApplyGuardrail`. P06 uses the latter
at application-controlled input, source and output boundaries, as specified in the plan.
The service also supports denied topics, word lists, PII detection, contextual grounding
and Automated Reasoning checks; those are not enabled or claimed here. In particular,
a filter pass is not a factuality assessment or authorization.

## Retrieval contract

Every retrieval is semantic, limited to 1–5 results, and filtered by the fixed service and
corpus version. No reranker or cached answers are used. The package contains a provenance
manifest with metadata and hashes, not the runbook text or evaluator answer keys.
For each returned passage, the adapter checks the S3 URI, passage/document IDs, version,
owner, validity dates, current/stale/conflicting status and frozen text hash. The only
text normalization permitted is stripping outer whitespace from the no-chunking parser.
Unknown, duplicate, empty, paginated, altered or incomplete results stop the investigation.

Stale and conflicting guidance is deliberately retained; it is never relabeled current
or silently excluded to make a rollback pass. The controller rejects rollback proposals
when retrieved guidance is stale/conflicting or outside validity dates. Model citation IDs
must refer to actual collected evidence. Semantic support still needs P08 review.
Evidence timestamps use the synthetic incident clock for reproducibility; actual retrieval
time and AWS request ID are recorded separately in the audit.

## Boundary and spending controls

`ApplyGuardrail` uses `guard_content` qualifiers with source INPUT for incident/source
text and OUTPUT for generated decisions. Missing/partial coverage, any service error,
an unknown action or an intervention stops processing. There is no unfiltered fallback.
Model output is checked before the controller accepts it or schedules the next tool.
The maximum is 47 checks of at most 32 KiB each: one input, eight tools with at most five
passages each, and six model decisions. Worker execution remains bounded to 120 seconds.

The local and DynamoDB ledgers retain $0.75 per Lite investigation or $2.50 per Pro
investigation, including failures. These reservations cover the existing conservative
full-context model bound, retrieval/query embeddings and bounded filtering; infrastructure
has its separate reserve. At $0.15 per 1,000 content-filter text units, a 47 × 33-unit
filter maximum is $0.23265. Regex checks are free at the checked pricing. Six full-context
Lite calls add at most $0.11016 at the retained P04 rate. These are planning bounds, not
an AWS bill. The $10 batch, global allowance and one-worker lease remain enforced.
Direct P06 ingestion/verification/probe commands each reserve $0.75 in both ledgers.
Never reset or refund either ledger. Replan the P08 matrix before running it.

Logs retain boundary, policy version, coverage, intervention, usage and AWS request IDs,
not assessed text or matched values. Raw model invocation logging was read back as disabled.
PII masking alone would not sanitize raw invocation logs; this demo neither ingests real
PII nor claims PII protection. Production would also need an IAM/account enforcement design:
standalone checks are enforced by this application, not by an IAM requirement on every
Converse call. No account- or organization-wide Guardrail setting was changed.

## Build, deploy and replay

Use the pinned tools from the P04/P05 runbooks. In PowerShell from the repository root:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
.venv/Scripts/python.exe -m pytest -q
infra/.venv/Scripts/python.exe infra/manage.py diff --retrieval
infra/.venv/Scripts/python.exe infra/manage.py deploy --retrieval
.venv/Scripts/python.exe scripts/package_live.py
infra/.venv/Scripts/python.exe infra/manage.py diff --live
infra/.venv/Scripts/python.exe infra/manage.py deploy --live
```

The live deployment reads the exact resource IDs from `infra/cdk.out/retrieval-outputs.json`.
If outputs are missing on a fresh checkout, a retrieval-stack deploy recreates that output
file. The committed `knowledge_base_id` in `infra/config.json` binds the KB role's trust to
the existing KB. For an explicitly authorized clean rebuild, omit that ID for initial
creation, then pin the new returned ID and redeploy the narrowed trust.

Initial installation uses `infra/prepare_retrieval_policy.py` to validate and attach a
separate scoped CFN policy. P04/P05 execution policies stay unchanged. Corpus upload is
create-only; do not rerun it against existing objects or replace the frozen corpus in place.
Each command below requires a new evidence directory and consumes an explicit reservation
except `upload` and read-only `inventory`:

```powershell
.venv/Scripts/python.exe scripts/p06_check.py upload --output runs/p06-upload-new
.venv/Scripts/python.exe scripts/p06_check.py ingest --output runs/p06-ingest-new
.venv/Scripts/python.exe scripts/p06_check.py verify --output runs/p06-verify-new
.venv/Scripts/python.exe scripts/p06_check.py probes --output runs/p06-probes-new
.venv/Scripts/python.exe scripts/live_smoke.py --batch p06-dev-01 --variant V0 --output runs/p06-v0-new
.venv/Scripts/python.exe scripts/p06_check.py inventory --output runs/p06-inventory-new
```

Only ingest after verifying the source and allowance. Ingestion must finish COMPLETE with
zero failures before retrieval is accepted. `verify` checks all eight passages and benign/
attack filter samples. `probes` explicitly uses offline model/tool doubles with real AWS
Guardrails to test controller blocks and service errors; it is not an end-to-end model run.
The live smoke runner always stops the AgentCore session and retains failures.

## Audit and cleanup

The existing private CloudTrail now includes exact KB and Guardrail data-event selectors.
Delivery is asynchronous. `collect_live_evidence.py --batch p06-dev-01 --output <new-folder>`
collects bounded logs and recent delivered trail records. `verify_p06.py --output <new-file>`
checks artifacts, package hashes, pinned runtime settings, trust and ledger reconciliation.

Both stacks are termination-protected; vector bucket, index, KB, data source and Guardrail
resources have RETAIN policies. Disabling use does not delete them. For later authorized
cleanup, inventory and export evidence first, then remove data source/KB, vector contents,
index and bucket in dependency order, followed by the dedicated KB role and Guardrail.
Data source deletion uses RETAIN and does not itself erase vectors. Retained S3 versions,
audit logs, runtime artifacts, KMS, alarms and logs must be inventoried separately using the
P04/P05 cleanup runbooks. Do not delete shared foundation buckets to remove the P06 prefix.

## References checked October 5, 2026

- [KB S3 Vectors prerequisites](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html)
- [S3 data-source metadata](https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html)
- [Vector index CloudFormation properties](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-s3vectors-index.html)
- [Independent ApplyGuardrail API](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html)
- [Prompt-attack filtering](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html)
- [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [CloudTrail advanced selectors](https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_AdvancedFieldSelector.html)
