# P10 acceptance — in progress

Bill marked P09 green and requested P10 on October 7, 2026. P10 covers clean-environment
replay, the final five-to-seven-minute recording, evidence preservation and verified cleanup.
The accepted P08 demo limitations remain; P10 does not reopen the full model benchmark.

## Completed preparation

- Exported committed P09 revision `1b193fd065f896b0f44b37fa38d1def37c479066` into an isolated
  checkout and installed locked application, infrastructure and Node dependencies afresh.
- Passed 226 application tests, 21 infrastructure tests and nine UI logic tests in that checkout.
  Three additional P10 export tests cover callback/credential removal, immutable writes and
  safe CloudFormation YAML handling. Ruff, corpus and schema checks pass.
- Compared the clean checkout with all four application stacks: no differences. Retained package
  manifests and existing non-secret stack outputs were supplied as explicit replay inputs.
  This is not evidence of provisioning into an empty AWS account.
- Ran all four deployment commands from that clean environment successfully, each with no changes.
  Post-deployment readback confirms complete stack statuses, runtime 13 READY and no running workflows.
- Inventoried five stacks and 147 stack-managed resources. Exported five sanitized tables and
  92 current run JSON artifacts; verified 106 archive files against their hashes and matched
  workflow artifact references to the exported documents.
- Confirmed all recorded workflows are terminal. The P07 intake counter is 8 accepted / 2 live,
  leaving one live investigation slot under the existing limit. No counter was reset.

The retained local reservation total is **$65.45**, with **$174.55** of experiment allowance
remaining and $10 protected for infrastructure. Reservations are not AWS charges. No additional
paid model trial ran during this preparation; P10 has not refreshed actual billing.

## Evidence and scope

| Record | Purpose |
|---|---|
| [Clean-checkout validation](evidence/p10/clean-checkout-validation.json) | Revision, archive/asset hashes, fresh dependency installs and test results |
| [Initial readiness](evidence/p10/initial-readiness.json) | Existing workflow counters, terminal runs and cloud reservations |
| [Stack inventory](evidence/p10/initial-stack-inventory.json) | Exact physical resources and deletion/retention policies |
| [Additional inventory](evidence/p10/initial-additional-inventory.json) | Named project logs and separately created managed policies |
| [Export summary](evidence/p10/initial-summary.json) | Export scope and counts |
| [Artifact manifest](evidence/p10/initial-artifact-manifest.json) | Original object/version identifiers and exported-file hashes |
| [Deployment readback](evidence/p10/post-deploy-readback.json) | Stack/runtime readiness after the clean-environment no-change deployments |

Deployment transcripts: [foundation](evidence/p10/clean-deploy-foundation.txt),
[live](evidence/p10/clean-deploy-live.txt), [retrieval](evidence/p10/clean-deploy-retrieval.txt),
and [workflow](evidence/p10/clean-deploy-workflow.txt).

The complete local archive is `.tools/p10/aws-snapshot-02/`, intentionally outside Git. It contains
current run artifacts and sanitized table state, not every S3 object version or every audit log.
Copy needed archives to your chosen retained location before final deletion. A final capture must
include any new recording runs. Callback tokens and temporary credentials are excluded.

Windows shared pytest temporary-directory permissions caused initial setup failures. Fresh,
workspace-contained `--basetemp` directories resolved them without changing the tested source.
The first inventory attempt encountered a YAML bootstrap template; the capture tool now parses
CloudFormation intrinsic tags safely. Partial attempts are retained separately and are not final evidence.

## Remaining gates

1. Record the live walkthrough and retain its run IDs, actual outcomes, final video path/hash and
   duration. One live intake slot is being preserved for this. Owner narration preference is pending.
2. Refresh/export final evidence, review the exact cleanup scope, then execute and verify cleanup.
   Record all retained resources and remaining charge sources; no deletion has occurred.

See the [recording runbook](p10-recording-runbook.md) and [cleanup plan](p10-cleanup-plan.md).
P10 is not green, and no final video or verified resource deletion is claimed.
