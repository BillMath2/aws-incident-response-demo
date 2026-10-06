# P04 deployment and cleanup runbook

Use the demo profile, account `498084841421`, and `us-east-2`. The `org-admin` profile is
for organization inspection and must not be used to deploy this project. The commands
below create project resources; they do not implement P05-P07. The accepted limits are
$50 total and $10 per live batch. See [readiness and cost decisions](p04-aws-readiness.md).

## Install and validate locally

From the repository root in PowerShell:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.tools/python'
$env:JSII_RUNTIME_PACKAGE_CACHE_ROOT = Join-Path $PWD '.tools/jsii'
.\.tools\uv.exe sync --project infra --locked
Push-Location infra
npm.cmd ci --ignore-scripts --no-audit --no-fund
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe manage.py synth
Pop-Location
```

On Linux/macOS with uv on PATH, run `uv sync --locked` and `npm ci --ignore-scripts`
inside `infra`, then `uv run --locked pytest` and `uv run --locked python manage.py synth`.
Use Node 22.17.0 and Python 3.12.12 for the retained baseline. The infrastructure has its
own Python and npm lockfiles; do not upgrade the application lock to install CDK.
CDK CLI and CDK library versions use separate release numbers.

The synth runs an explicit cdk-nag AWS Solutions scan and refuses violations. The access-log
bucket's recursive-access-logging rule has the sole documented acknowledgment. Both buckets
still require TLS, encryption, disabled ACLs and blocked public access. A negative test
ensures the scanner detects an unprotected bucket. CI performs these offline checks on
Windows and Linux without AWS credentials or paid calls.

If Windows test caches created by a different user deny access, select a fresh repository
test directory with `pytest -p no:cacheprovider --basetemp ../runs/unique-test-directory`.
Do not remove another user's cache or reuse a directory containing evidence.

## Readiness and budget

From `infra`, using its environment:

```powershell
.\.venv\Scripts\python.exe manage.py identity
.\.venv\Scripts\python.exe preflight.py --output ../runs/new-preflight.json
.\.venv\Scripts\python.exe budget.py
```

Review `config.json`, `models.json`, and the retained price snapshot. Preflight checks actual
availability fields and active profiles; API success alone is insufficient. Read-only list
checks prove access to those operations, not service creation, model quality, or runtime
permissions. New evidence paths are required so earlier results are preserved.

The optional paid smoke is exactly three fixed synthetic Converse requests, with 32 output
tokens each and SDK retries disabled. It reserves $0.10 in `runs/p04-budget-ledger.json`
before invoking anything. The ledger retains the reservation even after success; compare
its conservative reservations with recorded actual token estimates and eventual AWS billing.

```powershell
.\.venv\Scripts\python.exe model_smoke.py --output ../runs/new-model-smoke
```

Do not delete/reset the ledger to bypass limits. A leftover lock after process failure
requires checking that no smoke process is running, inspecting retained requests/reports,
and conservatively accounting for uncertain calls before removing only that lock file.
The ledger does not cover direct console/CLI calls outside this wrapper. P05 will extend
enforcement to live investigation batches.

## Bootstrap and deploy

Generate and review the exact execution policy:

```powershell
.\.venv\Scripts\python.exe deployment_policy.py
```

The reviewed document is `docs/evidence/p04/cfn-execution-policy.json`. For a fresh target,
create IAM policy `incident-demo-cfn-execution` from that document using the demo profile.
Check `iam get-policy` first; never overwrite a same-named existing policy without comparing
its content. IAM Access Analyzer `validate-policy` must report no errors or security warnings.
Use UTF-8 JSON; avoid PowerShell's default UTF-16 output when generating CLI input files.

From the repository root, only when the policy does not already exist:

```powershell
aws iam create-policy --policy-name incident-demo-cfn-execution --policy-document file://docs/evidence/p04/cfn-execution-policy.json --tags Key=Project,Value=incident-demo --profile incident-demo --region us-east-2
```

Then from `infra`:

```powershell
.\.venv\Scripts\python.exe manage.py bootstrap
.\.venv\Scripts\python.exe manage.py diff
.\.venv\Scripts\python.exe manage.py deploy
.\.venv\Scripts\python.exe verify_foundation.py --output ../runs/new-foundation-verification.json
.\.venv\Scripts\python.exe manage.py diff
.\.venv\Scripts\python.exe manage.py deploy
```

Inspect the diff before the first deploy and any later update. Deployment uses the dedicated
`incident-demo-toolkit` with qualifier `incdemo`; it does not borrow or overwrite another
project's default `CDKToolkit`. The bootstrap CloudFormation role receives only the reviewed
P04 policy. An empty follow-up diff and no-op repeat deploy demonstrate repeatability;
they do not constitute a clean-account rebuild or drift detection.

Readback verifies private buckets, TLS policies, versioning/access logging, on-demand table
caps, deletion protection, TTL, PITR and log retention. Newly enabled TTL/PITR may need time
to settle; retain an initial failed readback and retry to a new evidence path if necessary.
Retain `cdk.out/nag-report.json`, the exact template, resource inventory, deploy results,
and readback output. Neither successful synthesis nor a list API can satisfy these gates.

For a failed deployment, inspect `cloudformation describe-stack-events` before retrying.
Do not widen the execution policy to AdministratorAccess. A retained resource from a failed
stack can cause a name collision; inventory it and review import/recovery rather than
deleting it blindly. The foundation deliberately creates no application execution roles.

## Cleanup and retained charges

P04 leaves the foundation deployed for P05. Before final teardown:

1. Stop live invocations and ingestion; reconcile in-flight batches and reservations.
2. Export needed evidence to a private local destination. Inventory all project stacks and
   stack resources, including later P05-P07 resources, and verify account/region again.
3. Review the exact resources to delete. Disable termination protection only on the intended
   project stack and run its reviewed CDK destroy. P04 buckets, state table and log group
   use RETAIN and will remain; destroying the stack alone is not cleanup.
4. After evidence export and explicit deletion authorization, empty only the two inventoried
   project buckets (include all object versions and delete markers), then delete those buckets.
   Disable deletion protection on `incident-demo-state`, delete it, and check any retained
   backups. Delete the exact foundation log group if its evidence is no longer needed.
5. Preserve `incident-demo-toolkit` while any project deployment depends on it. Its S3 assets
   and ECR images have their own storage costs; inventory and expire unused artifacts. Never
   remove the toolkit as a shortcut to application cleanup.
6. Verify deletions with the service APIs and review billing after its reporting delay.
   Record every retained resource and expected charge rather than reporting zero cost solely
   because a CloudFormation stack was deleted.

S3 run evidence expires after 30 days, older versions after 7 days, and access logs after
7 days. Runbook objects outside `runs/` and `smoke/` have no automatic expiry, so future
knowledge sources remain until explicitly cleaned up. No destructive cleanup is part of P04.
