"""Read-only investigator interfaces; execution is deliberately a separate contract."""

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from incident_demo.contracts.base import (
    Contract,
    Identifier,
    Release,
    ServiceId,
    Text,
    Timestamp,
)


class HealthArgs(Contract):
    service_id: ServiceId


class ChangesArgs(HealthArgs):
    window_minutes: Annotated[int, Field(ge=1, le=120)] = 60


class LogsArgs(HealthArgs):
    filter: Literal["errors", "dependency", "deployment"] = "errors"
    limit: Annotated[int, Field(ge=1, le=50)] = 20


class RetrievalArgs(HealthArgs):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    limit: Annotated[int, Field(ge=1, le=5)] = 3


class HealthCall(Contract):
    name: Literal["get_service_health"]
    arguments: HealthArgs


class ChangesCall(Contract):
    name: Literal["get_recent_changes"]
    arguments: ChangesArgs


class LogsCall(Contract):
    name: Literal["get_recent_logs"]
    arguments: LogsArgs


class RetrievalCall(Contract):
    name: Literal["retrieve_runbook"]
    arguments: RetrievalArgs


InvestigatorCall = Annotated[
    HealthCall | ChangesCall | LogsCall | RetrievalCall, Field(discriminator="name")
]
CALL_ADAPTER = TypeAdapter(InvestigatorCall)


class Health(Contract):
    kind: Literal["health"]
    service_id: ServiceId
    observed_at: Timestamp
    release: Release
    error_rate: Annotated[float, Field(ge=0, le=1)]
    latency_p95_ms: Annotated[float, Field(ge=0, le=120000)]
    dependency_state: Literal["healthy", "degraded", "unknown"]


class Change(Contract):
    change_id: Identifier
    changed_at: Timestamp
    kind: Literal["deployment", "configuration"]
    release: Release
    summary: Text


class Changes(Contract):
    kind: Literal["changes"]
    service_id: ServiceId
    items: Annotated[tuple[Change, ...], Field(max_length=20)]


class LogEntry(Contract):
    observed_at: Timestamp
    message: Annotated[str, Field(min_length=1, max_length=2000)]


class Logs(Contract):
    kind: Literal["logs"]
    service_id: ServiceId
    entries: Annotated[tuple[LogEntry, ...], Field(max_length=50)]
    truncated: bool


class Passage(Contract):
    kind: Literal["runbook"]
    service_id: ServiceId
    passage_id: Identifier
    document_id: Identifier
    version: Identifier
    owner: Identifier
    valid_from: Timestamp
    valid_until: Timestamp
    status: Literal["current", "stale", "conflicting"]
    excerpt: Text

    @model_validator(mode="after")
    def ordered_validity(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("runbook validity end must follow start")
        return self


Payload = Annotated[Health | Changes | Logs | Passage, Field(discriminator="kind")]
