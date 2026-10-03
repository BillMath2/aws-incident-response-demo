"""One-process CLI walkthrough; exported JSON is evidence, not resumable authority."""

from datetime import timedelta
from time import perf_counter

from incident_demo.contracts.records import ExecuteRollback
from incident_demo.corpus import load_fixture, load_knowledge
from incident_demo.local_tools import observe_health
from incident_demo.workflow.local import LocalWorkflow, WorkflowError, identifier


def run_demo(args) -> int:
    if args.output and args.output.exists():
        raise ValueError("Output already exists; select a new file to preserve retained evidence")
    fixture = load_fixture(args.root / f"fixtures/cases/{args.case}.json")
    catalog = load_knowledge(args.root)
    began = perf_counter()

    def now():
        return fixture.incident.submitted_at + timedelta(seconds=perf_counter() - began)

    workflow = LocalWorkflow()
    record = workflow.start(fixture, catalog, idempotency_key=identifier("intake"), now=now())
    run_id = record.run.run_id
    output = args.output or args.root / "runs" / f"{run_id}.json"
    print(record.label)
    print(f"Run: {run_id}\nInvestigation: {record.investigation.outcome}")
    for fact in record.investigation.facts:
        print(f"- {fact.statement} [{', '.join(fact.evidence_ids)}]")
    print(record.investigation.justification)
    status = 0
    try:
        proposal = record.proposal
        if proposal:
            print("\nExact proposal for review:")
            print(proposal.model_dump_json(indent=2))
            decision = args.decision
            reviewed_hash = proposal.proposal_hash
            if decision is None:
                try:
                    decision = input("Decision [approve/reject/pending]: ").strip().lower()
                    if decision in {"approve", "reject"}:
                        reviewed_hash = input("Paste the reviewed proposal_hash: ").strip()
                except EOFError:
                    decision = "pending"
                    print("No decision received; preserving an unapproved proposal.")
            else:
                print(f"Scripted simulated decision: {decision} as {args.actor}")
            if decision not in {"approve", "reject", "pending"}:
                raise WorkflowError("Decision must be approve, reject or pending")
            if decision != "pending":
                record = workflow.decide(
                    run_id,
                    actor=args.actor,
                    proposal_hash=reviewed_hash,
                    decision="approved" if decision == "approve" else "rejected",
                    reason=args.reason,
                    now=now(),
                )
                if decision == "approve":
                    command = ExecuteRollback(
                        proposal_id=proposal.proposal_id,
                        approval_id=record.approval.approval_id,
                        idempotency_key=f"action-{run_id}",
                    )
                    receipt = workflow.execute(run_id, command, actor="local-executor", now=now())
                    print(
                        f"Synthetic action receipt: {receipt.receipt_id}; "
                        "recovery is not yet verified."
                    )
                    observed_at = now()
                    try:
                        observation = observe_health(
                            args.root, args.verification, observed_at, identifier("verification")
                        )
                    except (ValueError, OSError):
                        print(
                            "Independent health observer failed; the incident remains unresolved."
                        )
                        observation = None
                        status = 2
                    workflow.verify(run_id, observation, now=now())
    except (WorkflowError, ValueError) as exc:
        # Do not echo invalid raw payloads or Pydantic input values into public CLI output.
        print(
            f"Local control rejected: {exc}"
            if isinstance(exc, WorkflowError)
            else "Local data validation failed; review the fixture or operator input."
        )
        status = 2
    except KeyboardInterrupt:
        print("\nWalkthrough interrupted; exporting the current state.")
        status = 130
    finally:
        workflow.export(run_id, output)
    final = workflow.snapshot(run_id)
    print(f"Final state: {final.run.state}")
    print(f"Sandbox release: {final.service.release} (revision {final.service.revision})")
    print(f"Evidence exported: {output}")
    return status
