"""Small, fixed-scope runtime and diagnostic envelopes."""

from typing import Annotated, Literal

from pydantic import Field

from incident_demo.contracts.base import Contract, Identifier
from incident_demo.contracts.experiments import LiveSettings, Variant
from incident_demo.contracts.tools import InvestigatorCall
from incident_demo.corpus import IncidentInput


class LiveRequest(Contract):
    run_id: Identifier
    batch_id: Identifier
    telemetry_id: Annotated[str, Field(pattern=r"^[a-f0-9]{24}$")]
    incident: IncidentInput
    variant: Variant = "V1"
    settings: LiveSettings
    operation: Literal["investigate", "permission_probe"] = "investigate"


class DiagnosticRequest(Contract):
    run_id: Identifier
    telemetry_id: Annotated[str, Field(pattern=r"^[a-f0-9]{24}$")]
    attempt: Annotated[int, Field(ge=1, le=8)]
    call: InvestigatorCall
