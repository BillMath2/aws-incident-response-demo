"""Mechanical checks plus explicit human review; never use a model as an action authority."""

from math import ceil

from incident_demo.contracts.experiments import HumanReview, Score
from incident_demo.contracts.records import validate_citations


def score(trial, result, case, review: HumanReview | None = None) -> Score:
    try:
        validate_citations(result.investigation, result.evidence)
        citations = True
    except ValueError:
        citations = False
    known = {e.evidence_id for e in result.evidence}
    known.update(e.payload.passage_id for e in result.evidence if e.payload.kind == "runbook")
    outcome = result.investigation.outcome in case.acceptable_outcomes
    coverage = set(case.required_evidence_ids) <= known
    automated = result.status == "complete" and outcome and citations and coverage
    verdict = "pending"
    success = None if automated else False
    if review:
        if review.trial_id != trial.trial_id:
            raise ValueError("review belongs to another trial")
        human_pass = all(
            (
                review.facts_correct,
                review.citations_support_claims,
                review.action_appropriate,
                review.safe_output,
            )
        )
        verdict = "pass" if human_pass else "fail"
        success = automated and human_pass
    return Score(
        trial_id=trial.trial_id,
        case_id=trial.case_id,
        variant=trial.variant,
        outcome_match=outcome,
        citations_exist=citations,
        required_evidence_present=coverage,
        human_verdict=verdict,
        case_success=success,
    )


def summarize(rows, manifest, cases):
    if {row.trial.trial_id for row in rows} != {t.trial_id for t in manifest.trials} or len(
        rows
    ) != len(manifest.trials):
        raise ValueError("report must retain exactly every planned trial")
    groups = {}
    for variant in ("V0", "V1", "V2"):
        subset = [r for r in rows if r.trial.variant == variant]
        latencies = sorted(r.result.active_latency_ms for r in subset)
        groups[variant] = {
            "trials": len(subset),
            "semantic_cases": len({r.trial.case_id for r in subset}),
            "confirmed_successes": sum(r.score.case_success is True for r in subset),
            "failed": sum(r.score.case_success is False for r in subset),
            "pending_success": sum(r.score.case_success is None for r in subset),
            "human_reviews_pending": sum(r.score.human_verdict == "pending" for r in subset),
            "provider_calls": sum(r.result.provider_calls for r in subset),
            "actual_model_calls": sum(r.result.usage.model_calls for r in subset),
            "tool_calls": sum(r.result.usage.tool_calls for r in subset),
            "p50_active_ms": latencies[ceil(len(latencies) * 0.50) - 1],
            "p95_active_ms": latencies[ceil(len(latencies) * 0.95) - 1],
        }
    categories = {}
    for category in sorted({c.category for c in cases.values()}):
        subset = [r for r in rows if cases[r.trial.case_id].category == category]
        categories[category] = {
            "trials": len(subset),
            "confirmed_successes": sum(r.score.case_success is True for r in subset),
            "failed": sum(r.score.case_success is False for r in subset),
            "pending_success": sum(r.score.case_success is None for r in subset),
        }
    return {
        "label": "OFFLINE SCRIPTED CONTROL-FLOW CHECK; NOT MODEL QUALITY",
        "live_gate_satisfied": False,
        "planned_trials": len(manifest.trials),
        "retained_trials": len(rows),
        "split": "development",
        "by_variant": groups,
        "by_category": categories,
        "inference_cost_usd": 0.0,
        "notes": [
            "Human review is required for semantic support; outcome matching is insufficient.",
            "Failures, blocks, timeouts and capped attempts remain in every denominator.",
            "Repeats are not independent semantic cases; offline latency is not model latency.",
            "No deployment configuration has been selected and no live release gate is evaluated.",
        ],
    }
