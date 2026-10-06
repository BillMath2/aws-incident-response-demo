"""Executable LangGraph strategies with explicit budgets and bounded hypothesis search."""

from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import ValidationError

from incident_demo.contracts.base import canonical_json
from incident_demo.contracts.experiments import (
    DECISION_ADAPTER,
    Branch,
    ChooseTool,
    ExperimentResult,
    Finish,
    LiveSettings,
    SearchReply,
    Settings,
    TraceEvent,
)
from incident_demo.contracts.records import Evidence, Investigation, Usage, validate_citations
from incident_demo.contracts.tools import CALL_ADAPTER
from incident_demo.corpus import IncidentInput
from incident_demo.investigator.providers import (
    ModelRequest,
    OfflineBoundaryPolicy,
    ToolFailure,
    TransientFailure,
    tool_call,
)


class Stop(Exception):
    def __init__(self, reason: str, status: str = "incomplete"):
        self.reason, self.status = reason, status


class GraphState(TypedDict):
    route: str


class Engine:
    """One engine per run. Providers must honor the remaining transport timeout passed in."""

    def __init__(
        self,
        root: Path,
        variant: str,
        incident: IncidentInput,
        provider,
        tools,
        settings: Settings | LiveSettings | None = None,
        policy=None,
        clock=perf_counter,
    ):
        if variant not in {"V0", "V1", "V2"}:
            raise ValueError("unknown variant")
        self.variant, self.incident, self.provider, self.tools = variant, incident, provider, tools
        self.settings = settings if settings is not None else Settings()
        if self.settings.mode == "aws_live" and policy is None:
            raise ValueError("live execution requires an explicit boundary policy")
        self.policy, self.clock = policy or OfflineBoundaryPolicy(), clock
        self.prompt = (
            (root / "prompts/shared-v1.txt").read_text(encoding="utf-8")
            + "\n"
            + (root / f"prompts/{variant.lower()}-v1.txt").read_text(encoding="utf-8")
        )
        self.run_id = f"experiment-{uuid4().hex}"
        self.evidence: list[Evidence] = []
        self.trace: list[TraceEvent] = []
        self.branches: tuple[Branch, ...] = ()
        self.round = self.provider_calls = self.tool_calls = 0
        self.phase = "gather"
        self.pending = None
        self.result = None
        self.used = False

    def remaining(self):
        remaining = self.settings.limits.deadline_seconds - (self.clock() - self.started)
        if remaining <= 0:
            raise Stop("deadline_exhausted")
        return remaining

    def log(self, event, detail, call=None):
        self.trace.append(
            TraceEvent(
                event=event,
                phase=self.phase,
                round=self.round,
                detail=detail,
                call=call,
                branches=self.branches,
            )
        )

    def boundary(self, name: str, text: str):
        self.remaining()
        try:
            allowed = self.policy.check(name, text)
        except Exception as exc:
            raise Stop("filter_unavailable", "failed") from exc
        self.remaining()
        self.log("boundary_checked", f"{name}: {'pass' if allowed else 'blocked'}")
        if not allowed:
            raise Stop("filter_blocked", "blocked")

    def invoke_tool(self, call):
        call = CALL_ADAPTER.validate_json(call.model_dump_json())
        for retry in range(self.settings.limits.retries + 1):
            remaining = self.remaining()
            if self.tool_calls >= self.settings.limits.tool_calls:
                raise Stop("tool_budget_exhausted")
            self.tool_calls += 1
            self.log("tool_attempt", f"attempt {retry + 1}", call)
            try:
                results = self.tools.invoke(call, timeout_seconds=remaining)
            except TransientFailure:
                self.log(
                    "tool_transient_failure", "Transient failure counts against total budget", call
                )
                if retry == self.settings.limits.retries:
                    raise Stop("tool_retry_exhausted") from None
                continue
            except (ToolFailure, TimeoutError):
                raise Stop("tool_unavailable") from None
            self.remaining()
            if not results:
                raise Stop("empty_tool_result")
            for item in results:
                item = Evidence.model_validate_json(item.model_dump_json())
                if item.source != call.name:
                    raise Stop("tool_source_mismatch", "failed")
                self.boundary("source", canonical_json(item))
                existing = next(
                    (e for e in self.evidence if e.evidence_id == item.evidence_id), None
                )
                if existing and existing != item:
                    raise Stop("evidence_id_collision", "failed")
                if not existing:
                    self.evidence.append(item)
            self.log("tool_observed", "Validated observations collected", call)
            return

    def model(self):
        for retry in range(self.settings.limits.retries + 1):
            remaining = self.remaining()
            if self.provider_calls >= self.settings.limits.model_calls:
                raise Stop("model_budget_exhausted")
            self.provider_calls += 1
            request = ModelRequest(
                run_id=self.run_id,
                variant=self.variant,
                phase=self.phase,
                round=self.round,
                incident=self.incident,
                evidence=tuple(self.evidence),
                branches=self.branches,
                system_prompt=self.prompt,
                response_schema=DECISION_ADAPTER.json_schema(),
                tool_schema=CALL_ADAPTER.json_schema(),
                remaining_model_calls=self.settings.limits.model_calls - self.provider_calls,
                remaining_tool_calls=self.settings.limits.tool_calls - self.tool_calls,
                temperature=self.settings.temperature,
                max_output_tokens=self.settings.max_output_tokens,
            )
            label = "Live model" if self.settings.mode == "aws_live" else "Offline provider"
            self.log("provider_attempt", f"{label} attempt {retry + 1}")
            try:
                raw = self.provider.respond(request, timeout_seconds=remaining)
            except TransientFailure:
                if retry == self.settings.limits.retries:
                    raise Stop("model_retry_exhausted") from None
                continue
            except TimeoutError:
                raise Stop("model_timeout") from None
            self.remaining()
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > 32768:
                raise Stop("oversized_model_output", "failed")
            self.boundary("output", raw)
            return DECISION_ADAPTER.validate_json(raw)

    def gather_node(self, state):
        self.boundary("input", canonical_json(self.incident))
        names = {
            "V0": (
                "get_service_health",
                "get_recent_changes",
                "get_recent_logs",
                "retrieve_runbook",
            ),
            "V1": (),
            "V2": ("get_service_health", "get_recent_changes"),
        }[self.variant]
        for name in names:
            self.invoke_tool(tool_call(name))
        self.phase = {"V0": "final", "V1": "decide", "V2": "seed"}[self.variant]
        return {"route": "model"}

    def update_search(self, reply: SearchReply):
        candidates = reply.candidates
        ids = [c.candidate_id for c in candidates]
        if len(set(ids)) != len(ids) or len({c.cause for c in candidates}) != len(candidates):
            raise Stop("duplicate_candidates", "failed")
        old = {b.candidate.candidate_id: b for b in self.branches}
        if old and set(ids) != set(old):
            raise Stop("candidate_identity_changed", "failed")
        known = {e.evidence_id for e in self.evidence}
        known.update(e.payload.passage_id for e in self.evidence if e.payload.kind == "runbook")
        updated = []
        for candidate in candidates:
            if set(candidate.supporting_evidence + candidate.contradicting_evidence) - known:
                raise Stop("invented_search_citation", "failed")
            previous = old.get(candidate.candidate_id)
            if previous and candidate.cause != previous.candidate.cause:
                raise Stop("candidate_identity_changed", "failed")
            if previous and previous.status == "pruned":
                if candidate != previous.candidate:
                    raise Stop("pruned_branch_changed", "failed")
                updated.append(previous)
                continue
            score = len(candidate.supporting_evidence) - len(candidate.contradicting_evidence)
            pruned = self.round > 0 and (
                (candidate.contradicting_evidence and score <= 0)
                or (self.round == 2 and not candidate.supporting_evidence)
            )
            status = "pruned" if pruned else "supported" if score > 0 else "candidate"
            updated.append(Branch(candidate=candidate, score=score, status=status))
        self.branches = tuple(updated)
        self.log("search_state", reply.check_purpose, reply.next_check)
        if all(b.status == "pruned" for b in self.branches):
            self.result = self.fallback("escalate", "All hypothesis branches were pruned")
            return {"route": "end"}
        if self.round == 2 and reply.next_check is not None:
            raise Stop("search_round_limit", "failed")
        if self.round == 0 and reply.next_check is None:
            raise Stop("search_requires_check", "failed")
        if reply.next_check:
            self.pending = reply.next_check
            return {"route": "tool"}
        self.phase = "final"
        return {"route": "model"}

    def accept(self, reply: Finish):
        result = reply.investigation
        if result.run_id != self.run_id:
            raise Stop("wrong_run_id", "failed")
        validate_citations(result, tuple(self.evidence))
        if result.outcome == "propose_rollback":
            kinds = {e.payload.kind for e in self.evidence if e.complete}
            if not {"health", "changes", "logs", "runbook"} <= kinds:
                raise Stop("missing_proposal_evidence", "failed")
            self.check_proposal_preconditions()
            if self.variant == "V2":
                supported = [b for b in self.branches if b.status == "supported"]
                winners = (
                    [b for b in supported if b.score == max(x.score for x in supported)]
                    if supported
                    else []
                )
                if (
                    len(winners) != 1
                    or reply.selected_candidate_id != winners[0].candidate.candidate_id
                ):
                    raise Stop("search_selection_unsupported", "failed")
        self.result = result
        self.log(
            "finished", f"Accepted structured {result.outcome}; semantic support still needs review"
        )

    def check_proposal_preconditions(self):
        """Mechanical policy checks; semantic corroboration still needs human review."""
        by_kind = {e.payload.kind: e for e in self.evidence if e.payload.kind != "runbook"}
        health, changes, logs = (by_kind[k] for k in ("health", "changes", "logs"))
        now = self.incident.submitted_at

        def recent(at):
            return timedelta(0) <= now - at <= timedelta(minutes=5)

        if (
            not all(e.complete and recent(e.collected_at) for e in (health, changes, logs))
            or not recent(health.payload.observed_at)
            or health.payload.observed_at > health.collected_at
            or health.payload.release != "release-42"
            or health.payload.error_rate <= 0.01
            or health.payload.dependency_state != "healthy"
        ):
            raise Stop("proposal_preconditions_failed", "failed")
        deployments = [c for c in changes.payload.items if c.kind == "deployment"]
        deployment = max(deployments, key=lambda c: c.changed_at) if deployments else None
        if (
            not deployment
            or deployment.release != "release-42"
            or not timedelta(0) <= now - deployment.changed_at <= timedelta(minutes=120)
            or not logs.payload.entries
            or logs.payload.truncated
            or any(
                not recent(e.observed_at)
                or e.observed_at > logs.collected_at
                or e.observed_at < deployment.changed_at
                for e in logs.payload.entries
            )
        ):
            raise Stop("proposal_preconditions_failed", "failed")
        passages = [e.payload for e in self.evidence if e.payload.kind == "runbook"]
        if any(
            p.status != "current" or not p.valid_from <= now < p.valid_until for p in passages
        ) or not any(
            p.document_id == "rb-rollback" and p.owner == "checkout-operations" for p in passages
        ):
            raise Stop("proposal_preconditions_failed", "failed")

    def model_node(self, state):
        reply = self.model()
        if self.phase in {"seed", "update"}:
            if not isinstance(reply, SearchReply):
                raise Stop("unexpected_search_response", "failed")
            return self.update_search(reply)
        if isinstance(reply, ChooseTool) and self.variant == "V1":
            self.pending = reply.call
            self.log("tool_selected", reply.purpose, reply.call)
            return {"route": "tool"}
        if not isinstance(reply, Finish):
            raise Stop("unexpected_final_response", "failed")
        self.accept(reply)
        return {"route": "end"}

    def tool_node(self, state):
        self.invoke_tool(self.pending)
        if self.variant == "V2":
            self.round += 1
            self.phase = "update"
        return {"route": "model"}

    def fallback(self, outcome, reason):
        return Investigation(
            run_id=self.run_id,
            outcome=outcome,
            facts=(),
            hypotheses=(),
            missing_information=(reason,),
            next_check="Operator review or fresh diagnostic evidence",
            justification=f"{self.settings.mode} controller: {reason}",
        )

    def run(self) -> ExperimentResult:
        if self.used:
            raise ValueError("An engine cannot be reused across independent trials")
        self.used = True
        self.started = self.clock()
        graph = StateGraph(GraphState)
        graph.add_node("gather", self.gather_node)
        graph.add_node("model", self.model_node)
        graph.add_node("tool", self.tool_node)
        graph.add_edge(START, "gather")
        for node in ("gather", "model", "tool"):
            graph.add_conditional_edges(
                node, lambda state: state["route"], {"model": "model", "tool": "tool", "end": END}
            )
        status, reason = "complete", "finished"
        try:
            # Explicitly suppress remote tracing even if inherited environment enables LangSmith.
            with tracing_context(enabled=False):
                graph.compile().invoke({"route": "model"}, {"recursion_limit": 32, "callbacks": []})
        except Stop as exc:
            status, reason = exc.status, exc.reason
        except (ValidationError, ValueError):
            status, reason = "failed", "contract_or_citation_invalid"
        except Exception:
            status, reason = "failed", "adapter_failure"
        if status != "complete":
            self.result = self.fallback("incomplete", reason)
            self.log("stopped", reason)
        return ExperimentResult(
            run_id=self.run_id,
            variant=self.variant,
            mode=self.settings.mode,
            status=status,
            stop_reason=reason,
            investigation=self.result,
            evidence=tuple(self.evidence),
            trace=tuple(self.trace),
            provider_calls=self.provider_calls,
            usage=Usage(**getattr(self.provider, "usage", {}), tool_calls=self.tool_calls),
            active_latency_ms=max(0, int((self.clock() - self.started) * 1000)),
        )
