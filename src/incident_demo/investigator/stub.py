"""Conservative serializer-pattern stub for local plumbing, not model-quality evaluation."""

from datetime import datetime, timedelta

from incident_demo.contracts.records import Evidence, Finding, Hypothesis, Investigation


def investigate(
    run_id: str, evidence: tuple[Evidence, ...], missing: tuple[str, ...], now: datetime
) -> Investigation:
    facts: list[Finding] = []
    problems = list(missing)
    by_kind = {e.payload.kind: e for e in evidence if e.payload.kind != "runbook"}
    health = by_kind.get("health")
    changes = by_kind.get("changes")
    logs = by_kind.get("logs")
    passages = [e for e in evidence if e.payload.kind == "runbook"]
    for item in (health, changes, logs):
        if item is None:
            problems.append("A required diagnostic observation is missing")
        elif not item.complete:
            problems.append(f"{item.source} is incomplete")
        elif not timedelta(0) <= now - item.collected_at <= timedelta(minutes=5):
            problems.append(f"{item.source} collection time is stale or in the future")
    if health:
        value = health.payload
        facts.append(
            Finding(
                statement=(
                    f"Observed error rate {value.error_rate:.1%}, "
                    f"release {value.release}, dependency state {value.dependency_state}."
                ),
                evidence_ids=(health.evidence_id,),
            )
        )
        if not timedelta(0) <= now - value.observed_at <= timedelta(minutes=5):
            problems.append("Health observation is stale or in the future")
        if value.observed_at > health.collected_at:
            problems.append("Health observation is later than its collection time")
        if value.dependency_state != "healthy":
            problems.append("Healthy dependencies have not been established")
        if value.release != "release-42" or value.error_rate <= 0.01:
            problems.append("The sandbox rollback preconditions are not established")
    deployment = None
    if changes:
        deployments = [c for c in changes.payload.items if c.kind == "deployment"]
        if deployments:
            deployment = max(deployments, key=lambda c: c.changed_at)
            facts.append(
                Finding(
                    statement=f"Latest observed deployment is {deployment.release}.",
                    evidence_ids=(changes.evidence_id,),
                )
            )
        if (
            deployment is None
            or deployment.release != "release-42"
            or not timedelta(0) <= now - deployment.changed_at <= timedelta(minutes=120)
        ):
            problems.append("A recent release-42 deployment has not been established")
    supported = False
    if logs:
        if not logs.payload.entries or logs.payload.truncated:
            problems.append("Complete diagnostic logs are unavailable")
        for entry in logs.payload.entries:
            if (
                not timedelta(0) <= now - entry.observed_at <= timedelta(minutes=5)
                or entry.observed_at > logs.collected_at
            ):
                problems.append("Relevant log observations are stale or inconsistent")
            if deployment and entry.observed_at < deployment.changed_at:
                problems.append("An error observation precedes the deployment")
            # Deliberately narrow development-stub pattern. No case IDs or evaluator labels.
            text = entry.message.lower()
            if all(
                word in text for word in ("release-42", "release-41", "serializer", "typeerror")
            ):
                if "succeeded" in text or "baseline succeeds" in text:
                    supported = True
        if supported:
            facts.append(
                Finding(
                    statement=(
                        "Logs report release-42 serializer errors "
                        "and a successful release-41 baseline."
                    ),
                    evidence_ids=(logs.evidence_id,),
                )
            )
    if not supported:
        problems.append("The local stub cannot corroborate its known serializer regression pattern")
    current_policy = False
    for item in passages:
        passage = item.payload
        if passage.status != "current" or not passage.valid_from <= now < passage.valid_until:
            problems.append("Retrieved guidance is stale or conflicting; owner review is needed")
        if (
            passage.document_id == "rb-rollback"
            and passage.owner == "checkout-operations"
            and passage.status == "current"
            and passage.valid_from <= now < passage.valid_until
        ):
            current_policy = True
            facts.append(
                Finding(
                    statement="Current guidance requires separate approval and verification.",
                    evidence_ids=(item.evidence_id,),
                )
            )
    if not current_policy:
        problems.append("Current checkout rollback guidance is unavailable")
    incomplete = bool(missing) or any(not e.complete for e in (health, changes, logs) if e)
    outcome = "incomplete" if incomplete else "escalate" if problems else "propose_rollback"
    return Investigation(
        run_id=run_id,
        outcome=outcome,
        facts=tuple(facts),
        hypotheses=(
            Hypothesis(
                cause="Deployment regression",
                status="supported" if not problems else "candidate",
                supporting_evidence=(logs.evidence_id,) if logs and supported else (),
            ),
        ),
        missing_information=tuple(dict.fromkeys(problems)),
        next_check="Ask an operator to refresh or reconcile the missing evidence"
        if problems
        else None,
        justification="LOCAL STUB: "
        + (
            "; ".join(dict.fromkeys(problems))
            if problems
            else (
                "Fresh diagnostics match the known serializer regression pattern. "
                "Propose a sandbox rollback for human review."
            )
        ),
    )
