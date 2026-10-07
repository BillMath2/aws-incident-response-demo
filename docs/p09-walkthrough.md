# Draft walkthrough: six minutes

Rehearse with `scripts/p09_operator.py` in saved-evidence mode. This script uses retained
AWS results with clear on-screen labels. It is not a fresh execution or P10 recording.

| Time | On screen | Talk track |
|---|---|---|
| 0:00–0:40 | Incident desk and demo scope | “This is a synthetic checkout incident. The investigator gathers evidence and proposes a next step; a human owns action approval.” |
| 0:40–1:50 | Open recorded model investigation case-001; expand health, changes, logs and runbook | “These are retained Nova Lite/V2 results from AWS. Each claim points to a source. We distinguish an observed error rate from a hypothesis about its cause.” |
| 1:50–2:30 | Hypotheses and complete record | “The loop is bounded, and the trace records search decisions. Eight latest trials pass mechanical checks. Reasoning limitations are accepted for this demo; we have not proved production accuracy.” |
| 2:30–3:35 | Open recorded control: resolved; proposal hash and timeline | “This separately labeled control demonstrates approval and execution. The actual approver reviews the exact hash before expiry. A stored approval, not a model output or a button, authorizes the sandbox executor.” |
| 3:35–4:15 | Receipt and independent verification record | “The receipt proves the synthetic state change. A separate health observation establishes recovery. These are different records.” |
| 4:15–4:55 | Recorded unresolved, then rejected or expired | “Approval does not guarantee recovery. Unresolved stays unresolved. Rejection and expiry cannot become permission to act.” |
| 4:55–5:40 | Architecture and permission diagrams | “Step Functions owns durable business state. LangGraph owns bounded reasoning. IAM separates investigation from execution, with the documented same-owner identity limitation.” |
| 5:40–6:10 | Decision brief and next steps | “We chose code-defined control for reproducible experiments. We have no model-comparison or judge-quality claim. Production would need real telemetry, governed identities and held-out evaluation.” |

For a live walkthrough, launch with `--cloud` and explicitly call out that the existing workflow
uses V1, not the saved V2 trial. Starting a new investigation costs a retained $0.75 reservation
and consumes a bounded intake slot. The model may escalate or fail; narrate the real outcome.
If a proposal appears, the owner reviews the evidence and submits the decision. Do not check
human-review boxes automatically to manufacture a successful recording. Refresh status after
timeouts; reuse the same incident key until the outcome is known.

P10 owns the fresh deployment replay, final recording and verified cleanup. Before removing
anything, retain the required evidence and follow the dependency/retention instructions in
[P04 deployment](p04-deployment-runbook.md), [P05](p05-live-runbook.md),
[P06](p06-live-runbook.md) and [P07](p07-live-runbook.md). This P09 step removes no resources.
