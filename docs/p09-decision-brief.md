# Decision brief: a bounded incident-response demo

Use the existing code-defined LangGraph investigator on AgentCore, with Nova Lite and human
approval before any synthetic rollback. P08 is green **for the owner's demo scope**. Keep the
known reasoning limitations visible, and spend the remaining delivery effort on a clear operator
experience and reproducible walkthrough. This is a demonstration choice, not a production model
selection or proof that V2 is superior.

## What the measurements support

| Question | Decision and evidence |
|---|---|
| Which model? | Keep the already integrated Nova Lite. No Nova Pro development comparison was run, so no claim of model superiority is supported. |
| Which strategy? | Keep the existing V1 cloud workflow; show the latest V2 development records as a separate, labeled investigation example. Switching the workflow to V2 would need its own integration check. |
| What did additional search buy? | V2 exposes competing candidates and expansion/pruning in retained traces. Baseline variants and subsequent repairs differ in protocol/runtime; they do not isolate a causal benefit from additional search. |
| What is the latest result? | Runtime 13 produced eight mechanical candidates from eight development trials, with no format corrections. These checks establish allowed outcomes, citation existence and required evidence, not factual correctness. |
| Did a judge catch mistakes reliably? | No judge calls ran. There is no measured judge reliability result. Owner acceptance of reasoning limitations is not a fabricated judge score or factual label. |
| What remains outside acceptance? | Held-out quality testing, fair second-model comparison and detailed human semantic labels remain unfinished. The full evaluation scope needs budget reconciliation if resumed. |

The original 24 development trials and five separate eight-case repair batches total 64 attempts.
Do not combine different repair protocols into a fair model leaderboard. The latest repair corrected
an SDK conversion that removed required null alternatives from the actual tool schema. Fixing
that transport contract eliminated the observed mechanical failures in the latest batch; causal
interpretation errors still appear. See [P08 acceptance](p08-acceptance.md),
[review index](p08-review-index.md) and the [latest report](evidence/p08/repair-v5/report.json).

## Why code-defined control here?

The project requires explicit graph phases, bounded candidate search, deterministic validators,
frozen experiment variants, and inspectable traces. Those are already implemented and tested in
the code-defined investigator. Retain that implementation for this demo.

AWS's managed AgentCore harness offers a configuration-driven agent loop with managed runtime
services, tool connections and observability. It is a credible alternative when a configurable
loop is sufficient. We did not implement or benchmark a second harness, so the choice here is
about the project's control and reproducibility needs, not measured superiority over the managed
service. [AWS AgentCore harness documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html).

## When would Gateway be useful?

Keep direct, narrowly scoped diagnostic Lambda calls for the three current tools. Consider Gateway
when several agents need a shared tool catalog or integrations with different authentication
schemes. AWS documents conversion of APIs and Lambda functions into MCP tools with managed
authentication. That integration is optional here and was not deployed or benchmarked. The
sandbox action must remain outside investigator-accessible tools.
[AWS Gateway documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html).

## What would production adoption require?

Production needs separately governed analyst/approver identities, a reviewed service/action scope,
real telemetry and freshness rules, independent verification against real health signals, complete
operational logging, incident ownership and recovery procedures, and a quality evaluation on
representative held-out incidents. The localhost bridge is for one owner's demo, not remote users.
Budget reservations bound application experiments; they are not an account-wide billing cap.

The strongest demonstrated result is the control boundary: a model recommendation remains advisory,
approval binds to an exact stored proposal, the executor changes only synthetic state, and a separate
observation determines recovery. The [architecture and permissions](p09-architecture.md) and
[P07 acceptance evidence](p07-acceptance.md) support that claim within the documented demo scope.
