"""Process-local state and locking; no persistence or distributed atomicity claim."""

from dataclasses import dataclass, field
from threading import RLock

from incident_demo.contracts.local import LocalRunRecord
from incident_demo.contracts.records import ActionReceipt, ExecuteRollback, ServiceState


@dataclass
class MemoryStore:
    service: ServiceState = field(
        default_factory=lambda: ServiceState(
            service_id="checkout-api",
            release="release-42",
            revision=0,
        )
    )
    runs: dict[str, LocalRunRecord] = field(default_factory=dict)
    intake: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    actions: dict[str, tuple[ExecuteRollback, ActionReceipt]] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock)
