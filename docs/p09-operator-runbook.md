# P09 operator screen

The screen runs on localhost and uses the existing P07 IAM-authenticated API in Ohio.
It adds no hosted service, cloud resources or permissions. P08 is owner-approved green
for the demo scope, with reasoning limitations accepted and the full benchmark unfinished.

## Open the screen

From the repository root:

```powershell
cd C:\Github\aws-incident-response-demo
.\.venv\Scripts\python.exe .\scripts\p09_operator.py
```

Open **http://127.0.0.1:8765** in your browser. Use this exact address; alternate hostnames
are rejected. The default saved-evidence mode needs no AWS login and makes no AWS calls.
Choose a recorded model investigation or a recorded workflow control, then select
**Open recorded evidence**. Stop the server with Ctrl+C.

The eight P08 examples contain actual retained Nova Lite/V2 responses from runtime 13.
The four P07 controls show resolved, unresolved, rejected and expired outcomes. Controls
use labeled synthetic proposals, not model reasoning. Their investigation and verification
artifacts are checked against the stored hashes when loaded. No saved example is executable.

## Use the cloud workflow

With an active `incident-demo` AWS session:

```powershell
cd C:\Github\aws-incident-response-demo
.\.venv\Scripts\python.exe .\scripts\p09_operator.py --cloud --port 8766
```

Open **http://127.0.0.1:8766** for cloud mode. This separate port lets the saved-evidence
server remain on 8765. Run the command from the repository root, not `.venv\Scripts`.

The launcher validates account `498084841421`, reads `infra/cdk.out/workflow-outputs.json`
from the existing deployment, and uses `us-east-2`. If sign-in has expired, renew the existing
profile and restart. No credentials, AWS session tokens or callback tokens go to the browser.
Temporary assumed-role credentials refresh before expiry while the source session is valid.

1. Start an investigation with the generated incident key, or open an existing `p07-…` run ID.
2. Watch status refresh every five seconds. The existing cloud request uses Nova Lite/V1;
   saved P08 examples use V2. This screen does not change the deployed model or workflow.
3. Inspect findings, hypotheses, missing information and the expanded source material.
4. If a proposal is awaiting approval, review the service, target release, expiry and full hash.
   Paste that exact hash, enter a reason, and check both factual-support and citation reviews.
5. Select **Approve sandbox rollback** or **Reject proposal** and confirm the displayed run/hash.
   The server validates authority again. The screen cannot make expired or edited proposals valid.
6. Check the terminal outcome. Resolved requires the independent synthetic health observation;
   unresolved must not be narrated as successful recovery. Export the review JSON if useful.

The live API exposes the verification artifact reference/hash, not the full receipt or health
payload. Saved control examples show both from retained P07 evidence. Use the P07 evidence
capture tools for an administrative export; the operator bridge has no direct table/S3 reader.

Each new live investigation retains a **$0.75 reservation**, not a measured bill. The existing
$250 total, $10 per-batch and $10 protected infrastructure allowance remain unchanged.
The P07 intake counter also retains its limits of 32 accepted runs and three live investigations.
An exhausted allowance rejects intake; do not reset counters to make a recording work.

## Failures and recovery

A timeout can leave an unknown outcome. Refresh the run first. For intake, retry the **same key**;
generate a new key only for an intentionally new incident. The client does not automatically
retry mutations. Reservations are never automatically refunded. A failed or escalated investigation
does not turn into a controlled success or an executable saved proposal.

Cross-site requests, unexpected Host headers, missing page tokens, arbitrary cloud destinations,
control-test intake and malformed decisions are rejected. Model/source text renders as text,
with no HTML interpretation. Responses are uncached and the page uses a restrictive content policy.
The bridge is a single-owner localhost tool, not a multiuser authentication service; other programs
running as the same local user are within its trust boundary. Do not expose it through a tunnel.

The analyst and approver roles both trust the owner account role. They demonstrate distinct
effective permissions, not organizational separation of duties. AWS IAM, stored proposal hashes,
expiry and the conditional executor remain authoritative regardless of button state.

See [P09 acceptance](p09-acceptance.md), [architecture](p09-architecture.md),
[decision brief](p09-decision-brief.md), [walkthrough](p09-walkthrough.md), and
[P07 recovery and retention](p07-live-runbook.md).
