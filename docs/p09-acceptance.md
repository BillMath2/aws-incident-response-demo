# P09 acceptance — green for the approved demo scope

Bill reviewed P09 in both local and cloud modes and reported that it looks good on
October 7, 2026. This completes the operator-review gate and closes P09 for the demo.
See the [owner review record](evidence/p09/owner-review-2026-10-07.json).

Started October 7, 2026 after Bill marked P08 green for the agreed demo scope. P09 adds the
localhost operator screen and delivery documentation. No AWS resource, IAM policy, runtime
version, workflow limit or spending allowance was changed. The assistant's implementation
checks ran no new model calls or actions; the owner's review did not specify individual executions.

## Delivered

- Localhost screen for signed incident intake, status, evidence/citations, exact-hash approval
  or rejection, terminal result and JSON export through the existing cloud API.
- Read-only replay of eight retained P08 model investigations and four P07 workflow controls.
  Controls and model responses have distinct provenance labels; recorded proposals cannot execute.
- Server-held temporary AWS credentials, role refresh, strict destination/route validation,
  loopback binding, Host/origin/page-token checks, bounded request sizes and no mutation retry.
- [Operator runbook](p09-operator-runbook.md), [architecture and permission diagrams](p09-architecture.md),
  [decision brief](p09-decision-brief.md), and [six-minute walkthrough](p09-walkthrough.md).

## Verification

| Check | Result |
|---|---|
| Python suite | 226 passed, including 20 new operator/HTTP/SDK tests |
| UI logic | Nine Node tests passed; approval gating, expiry, recorded mode, literal untrusted text, confirmation cancellation, decision forwarding, run-switch reset, default example opening, empty selection feedback and load-error recovery |
| Formatting/lint | Ruff passes; 88 Python files formatted |
| Contracts | Corpus and generated schemas verified |
| Real cloud read | Local HTTP bridge signed an approver request and loaded an existing resolved run plus its immutable investigation |
| Cloud changes/model calls | None during assistant implementation checks; owner execution details not reported |
| Browser visual/interaction review | Owner reviewed local and cloud modes and accepted P09; automated browser review was unavailable |
| Hosted CI | Updated to run UI logic tests on Windows and Linux; no new hosted result claimed |

See the [validation record](evidence/p09/validation.json) and
[cloud readback](evidence/p09/cloud-readback.json). Python tests exercise actual local HTTP
requests; Node tests exercise the JavaScript controller against a minimal test DOM. These do
not establish visual layout or real-browser interaction quality.

Operator feedback identified a silent no-op when the saved-example selection was blank.
The screen now selects case-001 by default, reports loading/error states, and explains how
to select an example if cleared. The running server serves the fix and all 12 example endpoints
were checked successfully; this is an HTTP/logic verification, not a browser visual check.

## Completed operator review and P10 handoff

The owner accepted the local and cloud experience. That report does not establish a specific
fresh approval/execution, individual viewport checks or a new hosted CI result. These are not
claimed in the acceptance evidence. During P10's fresh walkthrough, the owner must review and
submit any real approval. The existing workflow uses V1; saved P08 trials use V2.

The live API returns a verification reference/hash, not the full health record or execution
receipt. Saved controls include retained, hash-checked health artifacts and receipts. The
screen's cloud result therefore relies on the existing backend's verified terminal status.
No claim is made that all P07 live controls were rerun for P09.

The full model comparison and held-out/judge evaluation remain outside the approved demo gate.
P10 still owns fresh deployment replay, final recording and verified resource cleanup.

## Review checklist

- Confirm recorded/live and model/control labels remain visible.
- Confirm displayed citations refer to visible source records; review semantic support yourself.
- Confirm no decision is enabled without both acknowledgments, exact hash, reason and unexpired proposal.
- Confirm uncertainty or failed verification remains explicit.
- Confirm SDK credentials and callback tokens never appear in browser output or exports.
- Use the same incident key after an unknown intake outcome; preserve reservations and counters.
- Preserve evidence before the separately planned P10 cleanup.
