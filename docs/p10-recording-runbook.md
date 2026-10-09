# P10 final recording runbook

Target five to seven minutes. Use the owner-reviewed P09 interface. Keep the existing Ohio
deployment available until the recording and evidence exports are checked.

## Open the cloud screen

From PowerShell, return to the repository root rather than changing into `.venv\Scripts`:

```powershell
cd C:\Github\aws-incident-response-demo
.\.venv\Scripts\python.exe .\scripts\p09_operator.py --cloud --port 8766
```

Open **http://127.0.0.1:8766**. If that server is already running, use its existing tab.
The saved-evidence screen can remain open on port 8765. Keep authentication windows and
terminal credentials out of the recording; the operator interface itself receives no AWS keys.

One live investigation slot remains as of the initial P10 readback. Start it when ready to
record, using one new incident key. After a timeout, reuse the same key and refresh status.
Do not generate extra keys for repeated takes: replay the saved run instead. The new run
retains $0.75 within the existing budget. Record its `p07-…` ID.

## Six-minute sequence

| Time | Demonstration | Accurate narration |
|---|---|---|
| 0:00–0:40 | Show the cloud screen and start one investigation | This is a live AWS investigation over synthetic checkout telemetry. The workflow currently uses Nova Lite/V1. |
| 0:40–1:50 | Watch status; open findings and source evidence | The model gathers evidence under fixed call, tool and time limits. Sources support review; citation existence alone does not establish correctness. |
| 1:50–2:30 | Show the actual proposal, escalation or failure | Narrate the real outcome. An escalation is a request for human follow-up, not successful remediation. |
| 2:30–3:50 | If a live proposal exists, manually review and approve/reject its exact hash; otherwise open the recorded resolved control | Identify recorded controls explicitly. They demonstrate authorization and synthetic execution, not a successful model diagnosis. Never present a prerecorded approval as live. |
| 3:50–4:30 | Show result and independent verification | The synthetic state receipt and later health observation are distinct. Unresolved stays unresolved. |
| 4:30–5:10 | Open saved case-004 or case-003, then an expired/rejected control | Label these retained records. Show unusable/missing evidence and how the workflow prevents unchecked action. |
| 5:10–6:20 | Architecture and decision brief | Explain Step Functions versus LangGraph responsibilities, eight latest mechanical candidates, accepted reasoning limitations, and the absence of a held-out model/judge comparison. |

The narrative can use the retained approval control if the live model escalates. That demonstrates
both paths honestly, but does not establish a new live model-to-approved-action success. Keep that
limitation in the final acceptance record. Do not use the automated P07 smoke approvals as human
factual-review attestations. A separately labeled live control test is possible if an interactive
approval demonstration is needed; prepare it only immediately before recording so it does not expire.

## Preserve the finished take

Export the displayed review JSON. Record the live run ID, actual terminal result, whether an action
occurred, and which sections use retained evidence. Save the video locally (for example under
`runs/p10-recording/`), then capture its SHA-256, duration and source revision. The final review
must confirm five-to-seven-minute duration, readable text, correct labels and no credentials or
callback tokens in the frame. No video has been created or inspected yet.

Refresh the AWS evidence archive after recording:

```powershell
.\.venv\Scripts\python.exe .\scripts\p10_capture.py --output .tools/p10/aws-snapshot-final
```

Use a new output folder for every capture; the tool refuses to overwrite an existing archive.
Then review the [cleanup plan](p10-cleanup-plan.md). Do not remove the cloud demo while it is
still needed for the final recording. [P09's decision brief](p09-decision-brief.md) and
[architecture diagrams](p09-architecture.md) are the presentation references.
