# AWS Incident Response Demo Master Implementation Plan

Date: October 3, 2026  
Prepared for: Bill Mathers  
Status: P01-P03 locally verified; P04-P07 AWS gates verified in Ohio; P08 owner-approved green for demo scope (full benchmark unfinished); P09 owner-reviewed green in local and cloud modes; P10 in progress: clean-environment deployments and evidence export complete, recording and cleanup pending; $250 total budget unchanged

Project destination: C:\Github\aws-incident-response-demo  
Target role: [Duke job description](DukeJob.txt)

P10 update (October 7, 2026): fresh dependency environments from the committed P09 source pass
226 application tests, 21 infrastructure tests and nine UI tests. All four existing application
stacks redeploy with no changes; this is not a new empty-account provisioning test. Five stacks,
147 resources, five tables and 92 current run artifacts are inventoried/exported. Runtime 13 is
READY and no workflows are running. One live intake slot is preserved for recording. No new
model calls or resource deletions ran. See [P10 acceptance](p10-acceptance.md),
[recording instructions](p10-recording-runbook.md) and [cleanup scope](p10-cleanup-plan.md).

P09 update (October 7, 2026): Bill marked P08 green for the demo and requested P09.
The localhost operator screen, signed cloud bridge, saved-evidence replay, architecture/permission
diagrams, decision brief and draft walkthrough are implemented. **226 Python tests and nine UI
logic tests pass.** The new bridge read an existing cloud run successfully, with no new model calls
or AWS changes. Bill subsequently reviewed local and cloud modes and accepted P09.
P10 owns the fresh replay, recording and cleanup verification. See [P09 acceptance](p09-acceptance.md) and
[launch instructions](p09-operator-runbook.md).

P08 update (October 7, 2026): after Bill explicitly approved the HIGH-to-MEDIUM prompt-attack
sensitivity change and all boundary checks passed, runtime 11 / Guardrail 2 ran the third V2
repair batch: six mechanical candidates and two schema failures. The previous source-filter and
candidate-selection failures cleared; factual quality remains unverified. The code passed 195
application / 21 infrastructure tests. Reservations are $52.70 of the approved $250. No held-out,
model-comparison or judge work ran. See [P08 acceptance](p08-acceptance.md) for retained evidence,
human-review needs and the remaining reservation shortfall.

Latest P08 update: runtime 13 / Guardrail 2 completed the fifth V2 repair with eight mechanical
candidates and no format corrections. A real LangChain transport test identified null stripping
in the SDK's tool conversion; native toolConfig now preserves the required nullable schema.
The fourth repair's four candidates/four failures remain retained. **206 application tests** pass.
Human semantic review and model quality remain unverified; case 006 even escalates before
retrieving the stale guidance. Reservations are $64.70, with the $250 ceiling unchanged.
The larger evaluation needs budget/scope reconciliation. No held-out or judge work has run.

Owner decision (October 7, 2026): Bill accepts the remaining reasoning issues for this synthetic
demo. Further paid reasoning-polish batches are no longer a demo priority, and these issues
alone do not block preparing P09's operator screen and walkthrough. Existing safety checks,
explicit action approval and spending limits remain in place. This does not mark the full
P08 evaluation complete or supply formal factual/citation labels. See the
[decision record](evidence/p08/demo-limitations-acceptance-2026-10-07.json).

Implementation update (October 3, 2026): P01 now has a pinned local environment, shared contracts
and JSON Schemas, eight versioned runbooks, twenty frozen cases (eight development / twelve
held-out), and offline CI configuration. See [P01 acceptance evidence](p01-acceptance.md) for
local check results and review limitations. Hosted CI and all live AWS gates remain unverified.
P02 update: the labeled local stub now presents proposals, accepts simulated approval/rejection,
applies an in-memory sandbox transition, independently verifies synthetic health, and exports
JSON evidence. See [P02 acceptance and retained walkthroughs](p02-acceptance.md).
P02 GitHub CI was reported green by Bill. M1 is locally demonstrated.

P03 update: versioned V0/V1/V2 prompts now run through bounded LangGraph control flow with a
scripted offline provider. The development harness freezes trial inputs, retains failures,
and separates automatic checks from human semantic review. See [P03 acceptance](p03-acceptance.md).
P03 does not claim live model quality or held-out evaluation.

P04 update (October 5, 2026): Bill selected `us-east-2` and approved $50 total / $10 per batch.
The project now has isolated, pinned CDK tooling, a scoped bootstrap execution policy,
private S3 storage, a capped on-demand DynamoDB table, and seven-day logs. Nova Lite,
Nova Pro and Llama 3.3 judge-model inference passed tiny readiness smoke calls. Bill selected
Titan Embeddings V2 with S3 Vectors for the P06 Knowledge Base. See
[P04 acceptance](p04-acceptance.md), [readiness decisions](p04-aws-readiness.md), and
[deployment/cleanup runbook](p04-deployment-runbook.md). Organization policies were not changed.
P05 update (October 5, 2026): AgentCore now runs the LangGraph investigator with actual
LangChain/Bedrock native tool calls and three scoped diagnostic Lambdas. A normal investigation,
one transient retry, model-call exhaustion, a forcibly stopped worker, IAM denials, private
evidence persistence and structured audit traces passed live checks. Repeated deployment made
no changes and stack drift is IN_SYNC. See [P05 acceptance](p05-acceptance.md) and the
[live runbook](p05-live-runbook.md). Diagnostics remain synthetic. Model quality, retrieval,
Guardrail coverage and durable cloud approval/action isolation remain later gates.
P05's conservative reservations require a budget reconciliation/replan before the P08 matrix;
at P05 completion the approved allowance remained $50 total / $10 per batch.
The design and estimates below are retained as the planning baseline.

P08 budget amendment (October 6, 2026): Bill approved a $250 total ceiling with the existing
$10 batch limit and $10 infrastructure reserve. Prior reservations are retained. The next
step is to review the now-complete frozen development baseline before model selection
and held-out evaluation. See the [approval record](evidence/p08/budget-approval-2026-10-06.json).

P06 update (October 5, 2026): eight frozen runbooks are indexed in the Ohio S3 Vectors
Knowledge Base. Live retrieval verifies passage metadata and hashes. Numbered Bedrock
Guardrails cover input, source and output; benign/attack and unavailable-service checks
pass. V0/V1 complete through the real AWS path. V2 stays bounded but its unsupported
proposal is rejected; this is retained as a P08 quality limitation, not a successful run.
See [P06 acceptance](p06-acceptance.md) and [operating runbook](p06-live-runbook.md).

Build one focused incident-response demonstration using LangGraph and LangChain on Amazon Bedrock AgentCore Runtime. Begin with a small local prototype, then prove live Bedrock inference, Knowledge Base retrieval, Guardrails, and an event-driven approval workflow on AWS. Compare three prompt strategies and two models using a controlled evaluation.

This master draft reconciles the two comparison documents and the two original plans. It is the proposed replacement for their implementation sequences. The source documents remain unchanged for reference. Work-package numbers below belong to this plan; they do not refer to the completed reconciliation workbench or map directly to either earlier plan.

**1 Evaluation of both comparison documents**

Sources reviewed:

- [AWS demo plans comparison](aws-demo-plans-comparison.md)
- [Plan comparison analysis](plan-comparison-analysis.md)
- [Original service-desk plan](agentic-service-desk-implementation-plan.md)
- [Original incident-response plan](aws-incident-response-demo-implementation-plan.md)

Both comparisons correctly favor the incident-response design, make AgentCore central, challenge the original estimate, and recommend reducing local duplication. They also agree that prompting experiments should cover the named job requirements more explicitly.

The first comparison is stronger on the judge's missing diagnostic evidence, the distinction between candidate selection and tree search, held-out evaluation, and separating model tests from transaction tests. These recommendations are adopted.

The second comparison adds useful proposals for Gateway, a managed-harness comparison, and a lightweight cross-family judge. These are evaluated individually rather than added wholesale. Several statements need qualification: the Classic restriction depends on account eligibility; retrieval is not inherently a model call; an agent invocation can contain multiple model calls; and no cited evidence here establishes the references to Quill, Intake Triage, or Bill's management history. Those personal-project claims are not assumptions in this plan.

| Recommendation | Master-plan decision | Reason |
|---|---|---|
| Use the incident-response design | Adopt | One understandable scenario connects evidence, tool use, authorization, and verification |
| Make AgentCore and LangGraph core | Adopt | Matches the role and avoids a new dependency on Agents Classic |
| Require CoT, ReAct, and ToT experiments | Adopt with precise definitions | Demonstrate structured decomposition, adaptive tool use, and bounded branching; do not relabel three drafts as a search algorithm |
| Reduce the local phase | Adopt | Keep contracts, fixtures, and a CLI walkthrough; defer the browser interface and omit a durable SQLite application |
| Add a model-size comparison | Adopt | Measure model and prompt effects separately |
| Add a cross-family judge | Adopt as a small evaluation experiment | Calibrate it against human labels; keep it outside the execution and approval path |
| Add AgentCore Gateway and MCP tools | Optional extension | Useful integration evidence, but not required by the job; direct scoped Lambda tools satisfy the core tool requirement |
| Compare managed harness and code-defined agents | Required architecture decision brief | Explain the choice from documented capabilities; a second implemented runtime is optional |
| Enforce Guardrails at Gateway | Do not assume coverage | Core application checks must explicitly cover input, source content, and output; any Gateway route needs its own tests |
| Re-estimate at 50–70 hours | Directionally agree, replace with package estimates | Integration, evaluation review, and retries need an explicit contingency |
| Mark old plans superseded and begin implementation | Not performed by this drafting task | This document provides a consolidated draft; original files are preserved |

AWS states that Agents Classic stopped accepting new customers on July 30, 2026, while eligible existing accounts can continue using it. Therefore, saying the service-desk plan would inevitably fail for every account is too strong. The master design still uses AgentCore for this new project. [AWS maintenance guidance](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html)

**2 Demonstration outcome and boundaries**

The central incident is a fictional checkout API error spike following release-42. The investigator checks service health, changes, logs, and runbooks, distinguishes facts from possible causes, and proposes a rollback to release-41 only when the evidence and policy support it.

An authorized human reviews the exact proposal. A separate executor updates a sandbox service record and records an action receipt. A subsequent health observation determines the reported outcome. An action receipt alone is never presented as proof of recovery.

Core scope:

- One investigator, three diagnostic tools, one retrieval interface, and one allowed sandbox mutation.
- Five demonstration stories: deployment regression, dependency outage, incomplete evidence, injected source instructions, and a transient diagnostic failure.
- Approximately eight versioned runbooks, including stale and conflicting material.
- A local CLI prototype, followed by a small operator screen using the cloud API.
- Three prompt variants, a second-model comparison, and a small judge-calibration experiment.
- AWS infrastructure, meaningful tests, retained execution evidence, a decision brief, and a five-to-seven-minute recording.

The incidents, identities, telemetry, and service effects are synthetic. Cloud inference, retrieval, filtering, orchestration, and storage must actually execute for the AWS milestone. Updating the sandbox record is not a real deployment rollback.

Excluded from core scope: real customer systems, production remediation, arbitrary shell commands, external ticketing integrations, multi-tenancy, a second full agent implementation, and a polished general-purpose helpdesk interface. An owned toy service with real HTTP health observations can be a later extension; it is not required to claim completion of this scoped demo.

**3 Evidence mapped to the job**

| Job requirement | Required demonstration evidence |
|---|---|
| Bedrock agents and foundation models | Versioned LangGraph agent running on AgentCore, invoking actual Bedrock models with retained traces |
| Knowledge Bases | Live retrieval, document and passage identifiers, freshness metadata, and retrieval checks |
| Guardrails and responsible behavior | Tested content boundaries, recorded interventions, benign false-positive cases, and independent authorization controls |
| Lambda, Step Functions, EventBridge | Event-to-completion execution with diagnostic Lambdas, approval wait, retries, and isolated action execution |
| CoT, ReAct, ToT | Versioned prompt experiments with observable task decomposition, adaptive tools, and bounded hypothesis branching |
| Evaluation and optimization | Frozen test corpus, expected outcomes, repeat runs, human review, cost and latency measurements, and model comparison |
| LangChain and AgentCore | Framework integration and an architecture decision explaining code-defined control versus the managed harness |
| Independent engineering and review | Typed contracts, CI, reproducible deployment, failure tests, and a review checklist |
| Technical guidance | A short decision brief choosing an approach based on measured results and explaining production gaps |

The repository can show engineering and communication practices. Mentoring, leadership, and production operating experience still require genuine career examples; this demo does not manufacture that evidence.

**4 Architecture and responsibility boundaries**

Use Python with uv, Pydantic contracts, LangGraph, LangChain's Bedrock integration, AWS CDK, DynamoDB, private S3 artifacts, and structured CloudWatch logs. Pin supported versions during setup. Reuse investigation logic, validation, and tool schemas across local and AWS modes.

Local mode uses deterministic fixtures, an explicitly labeled stub investigator, an in-memory state adapter, and exported JSON run records. It tests behavior within a process and does not claim durable distributed recovery. Omit SQLite and an early local web application.

AWS flow:

```text
Signed CLI or localhost operator screen with authenticated server bridge
    -> API Gateway with authenticated intake and approval endpoints
    -> Lambda validates request and atomically stores request + dispatch record
    -> dispatcher publishes incident event to EventBridge
    -> Step Functions Standard
       -> Lambda bridge invokes AgentCore Runtime
          -> LangGraph investigator uses Bedrock model
          -> scoped read-only diagnostic Lambdas
          -> Knowledge Base retrieval
          -> explicit Guardrails checks
       -> deterministic validation and proposal persistence
       -> human approval wait
       -> separate sandbox action Lambda
       -> independent health observation
       -> final status and audit evidence
```

Step Functions owns business control flow. LangGraph owns the bounded investigation loop. IAM and application validation enforce access. Neither a model recommendation nor a guardrail pass grants permission.

The bridge must have an explicit request/response contract, timeout, payload limit, cancellation behavior, and run identifier. Large evidence belongs in S3 with validated references; do not pass unrestricted logs through workflow state. Prove a bounded invocation before building the full workflow. Do not assume a long-running agent session fits a synchronous Lambda call without measurement.

Use Standard workflows for callback-based approval. AWS documents the callback pattern and its differences from Express. [Step Functions integration patterns](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html)

An architecture decision compares the managed harness with a code-defined agent. Select code-defined LangGraph because controlled tool budgets and prompt-search experiments are explicit project goals. Distinguish documented capabilities from measured results; do not publish comparative runtime benchmarks without implementing and testing both.

Gateway remains optional. AWS documents conversion of Lambda functions and APIs into MCP-compatible tools, but adding this route would introduce authentication and integration work. If pursued, pilot one diagnostic tool, verify permissions and filtering, then choose one tool route for the recorded demo. The sandbox action must never become an investigator-accessible tool. [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)

**5 Tools and required records**

| Interface | Inputs | Evidence or effect |
|---|---|---|
| get_service_health | Allowed service ID | Observation time, error rate, latency, dependency state |
| get_recent_changes | Allowed service ID and bounded window | Deployment/configuration IDs, versions, times |
| get_recent_logs | Allowed service ID and bounded filter | Sanitized excerpts, timestamps, completeness and truncation flags |
| retrieve_runbook | Query and service metadata | Passage ID, document/version, owner, validity metadata, excerpt |
| rollback_demo_release | Server-validated proposal reference | Conditional sandbox state update and durable receipt; executor only |

Reject arbitrary URLs, paths, SQL, and shell commands. Validate tool results as well as arguments. Agent-visible data must not include evaluator answer keys or scenario labels that reveal the expected diagnosis.

Required records:

- Request: stable ID, authenticated principal, service scope, idempotency key, submission time.
- Run: request link, mode, state, model/prompt/tool/fixture versions, timing, usage, trace links.
- Evidence: immutable ID, source, collection time, source version, content hash, completeness, sanitized payload or private artifact reference.
- Investigation: supported facts, evidence links, competing hypotheses, missing information, proposed next check, concise justification.
- Proposal: canonical action arguments, expected service version, evidence references, expiry, hash.
- Approval: authenticated approver, authorized scope, proposal hash, decision, reason, expiry.
- Action receipt: idempotency key, proposal link, before/after state, status, audit time.
- Evaluation: case and split, variant/model/repetition, expected versus actual outcomes, usage, latency, human verdict.

Citations may refer to both tool observations and runbook passages. Existence checks catch fabricated IDs; semantic review determines whether the cited evidence actually supports the statement.

**6 Authorization and failure behavior**

1. Authenticate cloud intake and approval requests using temporary credentials and separately scoped analyst and approver roles. Derive actor identity from trusted authentication context, never a supplied role field.
2. Store callback tokens only on the server. The interface receives an approval ID. Tokens must not appear in URLs, browser storage, reports, or logs.
3. Bind approval to the canonical proposal hash, allowed service, expected current release, and expiry. Check these again immediately before execution. A changed proposal needs a new approval.
4. Store the sandbox mutation, approval consumption, and action receipt in one DynamoDB transaction with conditional checks. A retry after a committed action returns the receipt; it must not mutate the service again.
5. Persist intake and a dispatch record atomically. A bounded dispatcher retries publication; recovery scans pending records. Duplicate events are expected. Use stable run identity and conditional transitions to prevent duplicate business effects.
6. Return the same run for a matching idempotency key and payload; reject key reuse with a different payload. Document retention and replay behavior.
7. A callback retry, duplicate decision, or timeout race must reconcile against stored state. A late callback cannot revive an expired or terminal run.
8. An agent or tool failure ends in an explicit retry, escalation, or failure state. No unchecked fallback is allowed when required filtering fails.
9. A later health observation is a separate evidence item. Failed verification means unresolved; it must not be rewritten as recovery.
10. Keep the investigator unable to approve or execute mutations. Verify effective runtime permissions, not just an intended IAM diagram.

Proposed investigation bounds are six model invocations, eight tool/retrieval calls, one retry per transient operation within those totals, and a 120-second investigation deadline. Freeze final bounds after development smoke tests. Exhaustion produces an explicit incomplete result. Business approval waiting has a separate configurable expiry, initially 15 minutes for the demo; enforce expiry in application logic rather than relying on eventual database TTL deletion.

Guardrails coverage must be explicit: check user input, relevant untrusted retrieved/tool text before model use, and generated output before acceptance. Record policy version, boundary, coverage, and intervention. Configure supported filters with the required input/output context and test each path. Guardrails are one signal alongside schema, citation, IAM, and approval checks. AWS provides ApplyGuardrail for checks at application-controlled boundaries. [ApplyGuardrail documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html)

**7 Required prompt and model experiments**

All variants use the same source corpus, allowed tools, output contract, guardrail configuration, and maximum budgets. Keep prompt/model versions, temperatures, retrieval settings, and cache behavior in the run manifest. Differences in actual work are measured rather than hidden.

| Variant | Definition | Observable evidence |
|---|---|---|
| V0 Structured decomposition | Fixed diagnostic gathering followed by one response prompted to assess symptoms, changes, corroborating evidence, uncertainty, and next action | Structured findings and concise justification; a CoT-style decomposition baseline without exposing private reasoning |
| V1 ReAct investigator | The model chooses diagnostic or retrieval tools, observes results, and decides whether to continue or conclude | Bounded tool/observation sequence and evidence-backed outcome |
| V2 Bounded hypothesis search | Maintain at most two candidate causes across at most two expansion rounds; choose a discriminating check, update supporting/contradicting evidence, prune unsupported branches, select or escalate | Recorded hypothesis states, selected checks, evaluation criteria, and stopping/pruning decisions |

V2 is a deliberately small Tree-of-Thought-style search. Merely generating multiple finished drafts is not sufficient. Public artifacts contain evidence summaries and decisions, not private chain-of-thought transcripts. [Tree of Thoughts research](https://arxiv.org/abs/2305.10601)

Compare V0, V1, and V2 using one base model. Select a strategy using development cases, then run that same strategy with a second, more capable candidate model. Hold all other settings steady. Use development runs of both model configurations to preselect the deployment candidate before the held-out batch. Two models are required for the comparison, but the larger model is not automatically the production recommendation.

The small judge experiment is separate from the action path: prepare 12 human-labeled drafts, six supported and six flawed, covering unsupported claims, bad citations, unsafe proposals, and valid uncertainty. Use a different-family model where regional access permits. Supply the request, runbook passages, diagnostic observations with timestamps, and draft; withhold author/model identity and self-scores. Report false accepts, false rejects, agreement, latency, and cost. The judge never authorizes an action or replaces human review. If access requires a third model, resolve that cost in AWS readiness.

**8 Evaluation design and acceptance gates**

Create 20 semantic incident cases before prompt tuning: eight development and 12 held-out cases. Freeze split, expected facts, acceptable actions/escalations, and corpus versions in a manifest. Near-duplicate paraphrases of a development case should not be the only held-out challenges.

Suggested held-out composition: four actionable incidents with sufficient evidence; three dependency, missing-evidence, or conflicting-evidence cases; three injection/exfiltration cases; and two stale-data or persistent-tool-failure cases. Include benign security-related language to measure false blocking.

Development cases support prompt tuning and selection. The held-out corpus is used for final reporting, not iterative prompt adjustment. If failures trigger changes, retain those results and create fresh held-out cases before claiming another unbiased confirmation. Freeze the chosen strategy/model before the final batch; report any failure of that choice instead of quietly selecting a winner after looking at test results.

Planned scored live runs:

- 12 held-out cases x 3 variants x 3 repetitions = 108 base-model investigations.
- 12 held-out cases x 1 preselected variant x 3 repetitions = 36 second-model investigations.
- Total: 144 scored investigations, plus 12 judge calls.
- Development calls, retrieval, guardrail checks, and infrastructure smoke runs are additional and separately budgeted. One investigation can contain several model calls.

Reset sandbox and agent session state between independent cases. Preserve failed attempts, timeouts, and capped runs in the denominator. Three repeats reveal some stochastic variation; they do not turn 12 scenarios into 36 independent problem types.

Run deterministic checks separately in ordinary CI:

| Test group | Required checks |
|---|---|
| W01 Contracts | Invalid JSON, unknown tools/targets, oversized results, invented citation IDs |
| W02 Authorization | Wrong actor, client-supplied privilege, agent attempting action or approval |
| W03 Approval binding | Edited arguments, stale release, expiry, duplicate decisions |
| W04 Dispatch | Failure before/after publication, duplicate delivery, recovery, dead-letter inspection |
| W05 Action recovery | Concurrent execution, timeout after commit, repeated invocation |
| W06 Terminal states | Rejection, late callback, approval timeout, retry exhaustion |
| W07 Evidence | Stale observations, missing data, valid citation ID supporting a false claim |
| W08 Verification | Failed health check stays unresolved, prior evidence remains immutable |

Some require real AWS integration and fault injection as well as unit tests. A model's answer cannot prove atomicity or effective IAM permissions.

Proposed release gates, frozen before final evaluation:

- At least 90% run-level case success for the preselected configuration, counting failures and inappropriate escalations.
- At least 90% appropriate actionable outcomes on sufficient-evidence cases; also report appropriate escalation and refusal by case category.
- All accepted citation IDs exist, and human review finds no unsupported material diagnosis or action claim.
- Zero observed unauthorized mutations, exposed synthetic secret canaries, approval bypasses, duplicate business effects, or false completed-recovery claims.
- Every required deterministic and AWS integration test passes; any critical control failure blocks release regardless of aggregate scores.

These are proposed gates, not achieved results or universal safety claims. Human review covers every scored investigation, including failures, blocked answers, and escalations. Any scope or target change must remain visible.

Report: case success by category; useful resolution and appropriate escalation; required and unnecessary tools; citation validity and claim support; attack success and benign false blocks; calls, tokens, estimated inference cost and other service usage; p50/p95 active latency with sample size. Exclude human waiting from active latency and report waiting separately. Note small-sample uncertainty.

**9 Work packages and dependencies**

Estimates are focused engineering hours for one developer, not elapsed commitments. P01-P03 have passed local acceptance; see the implementation updates above. Each package must produce retained acceptance evidence; a green offline CI run is not a live AWS gate.

| Package | Work | Depends on | Hours | Completion evidence |
|---|---|---|---|---|
| P01 | Scaffold, contracts, runbooks, case manifest | None | 4–6 | Reproducible local environment, schemas, versioned fixtures, declared dev/test split, lint/unit CI |
| P02 | Thin local end-to-end slice | P01 | 4–6 | CLI investigates with labeled stub, presents proposal, approves/rejects, applies synthetic transition, exports evidence; selected negative tests pass |
| P03 | Prompt variants and evaluation harness | P02 | 5–7 | V0/V1/V2 definitions, bounded search logic tests, scoring rubric, trial manifests, fault tests; no claims of live quality yet |
| P04 | AWS readiness and deployment foundation | P02 | 3–5 | Account/region/models, supported features, IAM matrix, resource and cost inventory, CDK baseline deploy/replay |
| P05 | Live investigator and diagnostic tools | P03, P04 | 6–9 | AgentCore invocation uses actual Bedrock and scoped Lambda tools; bounded timeout/error path and traces verified |
| P06 | Knowledge Base and Guardrails | P05 | 5–8 | Live retrieval and passage checks; explicit input/source/output coverage; attack and benign smoke results |
| P07 | Event workflow and durable approval/action | P06 | 6–9 | Event-to-completion trace, authenticated approval, dispatch recovery, conditional transaction, IAM denial and duplicate/timeout tests |
| P08 | Controlled experiments and human review | P07 | 6–9 | Frozen configuration, 144 scored investigations, 12 judge cases, human review, complete quality/cost/latency report |
| P09 | Operator screen, decision brief, documentation | P07; P08 for final content | 5–7 | Small localhost UI through cloud API, architecture/permission diagrams, choices linked to evidence, draft walkthrough |
| P10 | Clean replay, recording, cleanup verification | P08, P09 | 3–4 | Fresh deployment replay, retained sanitized evidence, five-to-seven-minute recording, verified resource cleanup and retained-cost list |

Core estimate: **47–70 focused hours**, plus **10–15 hours contingency**, giving a planning allowance of **57–85 hours**. At 15 hours per week, allow approximately four to six weeks, excluding account/access delays. Re-estimate after P02 and P05; the evaluation review time is especially uncertain.

The first local milestone is P02, after approximately 8–12 hours. P03 and AWS readiness need not be serialized once that milestone works, but this plan does not assume extra engineers.

Milestones:

- M1 after P02: local contract/workflow demonstration.
- M2 after P06: live grounded and filtered AWS investigator.
- M3 after P07: controlled event-driven cloud workflow.
- M4 after P10: evaluated, documented, recorded release.

If time is constrained, cut Gateway, a second harness implementation, visual polish, and the toy HTTP service first. Preserve the required prompt/model experiments, authorization controls, and live evaluation. An incomplete milestone can be presented honestly, but cannot be labeled a completed demonstration of all job requirements.

**10 AWS readiness and operating costs**

Choose the region, two compatible models, judge model, embedding model, and supported vector store in P04. Check both capability and price; do not copy old model IDs or silently switch to a continuously billed store. Record routing/data-region implications.

Agree a total experiment allowance and per-batch allowance before live work. Estimate from maximum model calls/tokens plus retrieval, guardrails, runtime, storage, ingestion, and logging. Budget notifications are not a hard stop; enforce application call and concurrency limits and track reserved versus actual batch usage.

Use temporary credentials, resource tags, short retention, and separate roles for intake, dispatch, investigator, diagnostic tools, approval, and execution. The local browser bridge keeps AWS credentials server-side, binds to localhost, and validates origin and mutation requests. No hosted anonymous approval endpoint is part of the demo.

Ordinary CI runs without AWS secrets or paid calls. Add explicitly configured live smoke and evaluation jobs after cloud integration exists. A fake provider response must never satisfy a live gate.

**11 Deliverables and presentation**

Keep one source tree with shared contracts and adapters:

```text
src/incident_demo/
  contracts/  investigator/  tools/  retrieval/
  workflow/  approval/  execution/  storage/
  cli/  api/  static/
prompts/  fixtures/  knowledge/
evals/  tests/  infra/  scripts/  docs/
```

Deliver README/setup instructions, architecture and permission diagrams, prompt/model manifests, evaluation report, sanitized run evidence, deployment and recovery runbook, cleanup procedure, code-review checklist, and a short decision brief.

The decision brief answers: Which strategy/model would we choose? What did additional search buy? Did the judge catch mistakes reliably? Why code-defined LangGraph rather than the managed harness? When would Gateway be worth adding? What would production adoption require?

The recording shows one live investigation, evidence and uncertainty, approval and verified sandbox outcome, an adversarial or missing-data case, and a concise evaluation comparison. Use a retained trace for failure/retry behavior if showing every case live would obscure the story. Label prerecorded evidence, local stubs, and simulated effects.

**12 Definition of done and planning status**

The master plan is ready for implementation review when its scope, milestones, unresolved AWS selections, and evaluation budget are understood. The original drafting task created documentation only; subsequent P01-P03 implementation is recorded in the updates above.

The implemented AWS demo is complete only when:

- A clean environment deploys and replays documented scenarios.
- Actual AgentCore, Bedrock, Knowledge Base, Guardrails, Lambda, EventBridge, and Step Functions behavior has retained evidence.
- The selected configuration meets the frozen evaluation gates and all critical workflow tests pass.
- Documentation and recording match the tested revision and clearly identify synthetic effects.
- Project-owned resources are inventoried before cleanup; retained evidence is exported; deletion and any remaining billable resources are verified.
- Unresolved limitations are stated, including the synthetic workload, small evaluation set, and absence of production customer operations.

Historical P08 checkpoint (superseded by the owner-approved demo gate and current P10 status):
All 24 frozen development trials are retained: seven mechanical candidates awaiting human review
and 17 mechanical failures. Runtime, prompts and corpus remained unchanged between batches.
Bill agreed with those 17 failure classifications. A separate eight-case V2 repair on runtime
version 9 fixed missing runbook collection in that batch, but produced one mechanical candidate
with a narrative error and seven failures. Retrieval/scenario alignment and model quality remain
unresolved; the original baseline and repair results are separate. Reservations total $38.45.
The second repair (runtime version 10) aligns live KB retrieval with the frozen scenario document
inventories and corrects the nullable selection schema. Five of eight results are mechanical
candidates, three fail, and factual concerns still require human review. Retained reservations
now total $44.45. A fair rerun of all strategies under these corrected settings plus the remaining
full evaluation projects $260.45 in reservations, exceeding the $250 ceiling; budget/scope
reconciliation is required before the larger evaluation. No held-out inference has run.
The budget increase is approved. Human review, the second-model comparison, final preselection, 144 held-out
investigations and 12 judge cases remain outstanding. See [P08 acceptance](p08-acceptance.md)
and the [P08 runbook](p08-evaluation-runbook.md). P08 was not green at this checkpoint;
the later owner decision accepted it for the demo scope with these evaluation limitations.
P07 passed 45 live control checks and 33 readback/permission checks, with a clean final deployment
diff. See [P07 acceptance](p07-acceptance.md) and the [P07 runbook](p07-live-runbook.md).
Gateway access logs are explicitly deferred after automatic approval review rejected account-level
log-delivery permissions; private Lambda request audits and API metrics are the narrower alternative.
P06 verifies retrieval and explicit filtering in Ohio; it does not satisfy the workflow or
model-quality gates. V2's rejected unsupported proposal remains visible in the P06 evidence.
P01-P03 did not deploy AWS resources. The original comparison plans remain unchanged.
