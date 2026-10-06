"""Control races use atomic repository semantics; AWS transaction behavior is checked live."""

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import RLock

import pytest
from pydantic import ValidationError

from incident_demo.workflow.durable import (
    Conflict,
    Control,
    Decision,
    Intake,
    actor_identity,
    advance,
    public,
)

APPROVER = "arn:aws:iam::498084841421:role/incident-demo-p07-approver"


class MemoryRepository:
    def __init__(self):
        self.data, self.lock = {}, RLock()

    def get(self, table, key):
        with self.lock:
            return copy.deepcopy(self.data.get((table, key)))

    def scan(self, table, prefix):
        return [
            (key, copy.deepcopy(value))
            for (t, key), value in self.data.items()
            if t == table and key.startswith(prefix)
        ]

    def commit(self, changes):
        with self.lock:
            for table, key, old, _ in changes:
                actual = self.data.get((table, key))
                if (actual or {}).get("_v") != (old or {}).get("_v"):
                    raise Conflict("concurrent transition")
            for table, key, old, new in changes:
                if new is not None:
                    self.data[table, key] = copy.deepcopy(new) | {"_v": old["_v"] + 1 if old else 1}


@pytest.fixture
def ready():
    clock = [datetime(2026, 10, 6, tzinfo=UTC)]
    c = Control(MemoryRepository(), lambda: clock[0])
    request = Intake(idempotency_key="test", scenario="control-recovery")
    run = c.intake(request, "analyst-role", "session")
    rid = run["run_id"]
    c.db.commit([("runs", "run#" + rid, run, advance(run, "investigating", clock[0]))])
    c.propose(rid, ["health"], {"key": "immutable-investigation"})
    c.wait(rid, "secret-token-never-public")
    return c, rid, clock


def decision(c, rid, **changes):
    return Decision(
        **(
            {
                "proposal_hash": c.db.get("runs", "run#" + rid)["proposal"]["proposal_hash"],
                "decision": "approved",
                "reason": "controlled test",
                "facts_reviewed": True,
                "citations_reviewed": True,
            }
            | changes
        )
    )


def test_intake_idempotency_and_payload_conflict(ready):
    c, rid, _ = ready
    assert (
        c.intake(
            Intake(idempotency_key="test", scenario="control-recovery"),
            "analyst-role",
            "new-session",
        )["run_id"]
        == rid
    )
    with pytest.raises(Conflict):
        c.intake(
            Intake(idempotency_key="test", scenario="control-unresolved"), "analyst-role", "session"
        )
    assert (
        c.intake(
            Intake(idempotency_key="test", scenario="control-recovery"), "another-role", "session"
        )["run_id"]
        != rid
    )


def test_signed_actor_not_client_privilege():
    event = {
        "role": "approver",
        "requestContext": {
            "authorizer": {
                "iam": {
                    "userArn": (
                        "arn:aws:sts::498084841421:assumed-role/incident-demo-p07-analyst/test"
                    )
                }
            }
        },
    }
    with pytest.raises(PermissionError):
        actor_identity(event, APPROVER)
    event["requestContext"]["authorizer"]["iam"]["userArn"] = (
        "arn:aws:sts::498084841421:assumed-role/incident-demo-p07-approver/test"
    )
    assert actor_identity(event, APPROVER)[0] == APPROVER


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "admin"},
        {"arguments": {"target_release": "release-40"}},
        {"facts_reviewed": False},
        {"reason": "x" * 501},
    ],
)
def test_unreviewed_or_edited_approval_contract(ready, extra):
    c, rid, _ = ready
    with pytest.raises(ValidationError):
        decision(c, rid, **extra)


def test_duplicate_conflicting_and_expired_decisions(ready):
    c, rid, clock = ready
    d = decision(c, rid)
    assert c.decide(rid, d, APPROVER, "s")["status"] == "approved"
    assert c.decide(rid, d, APPROVER, "new-session")["status"] == "approved"
    with pytest.raises(Conflict):
        c.decide(rid, decision(c, rid, decision="rejected"), APPROVER, "s")
    clock[0] += timedelta(minutes=16)
    with pytest.raises(Conflict):
        c.execute(rid, APPROVER)
    assert c.db.get("sandbox", "service#" + rid)["revision"] == 0


def test_concurrent_execute_and_unknown_commit_retry(ready):
    c, rid, _ = ready
    c.decide(rid, decision(c, rid), APPROVER, "s")
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: c.execute(rid, APPROVER), range(12)))
    assert all(r == receipts[0] for r in receipts)
    assert c.db.get("sandbox", "service#" + rid)["revision"] == 1
    assert c.db.get("approvals", rid)["status"] == "consumed"
    # Simulates caller losing the committed response; subsequent invocation returns same receipt.
    assert c.execute(rid, APPROVER) == receipts[0]


@pytest.mark.parametrize(
    "fault", ["stale_release", "edited_hash", "wrong_actor", "rejected", "terminal"]
)
def test_executor_revalidates_authority(ready, fault):
    c, rid, _ = ready
    c.decide(
        rid,
        decision(c, rid, decision="rejected" if fault == "rejected" else "approved"),
        "other" if fault == "wrong_actor" else APPROVER,
        "s",
    )
    if fault == "stale_release":
        c.db.data["sandbox", "service#" + rid]["release"] = "release-41"
    if fault == "edited_hash":
        c.db.data["runs", "run#" + rid]["proposal"]["proposal_hash"] = "0" * 64
    if fault == "terminal":
        c.finish(rid, "expired")
    with pytest.raises((Conflict, ValidationError)):
        c.execute(rid, APPROVER)
    assert c.db.get("sandbox", "receipt#" + rid) is None


def test_timeout_after_commit_is_unresolved_and_cannot_revive(ready):
    c, rid, _ = ready
    c.decide(rid, decision(c, rid), APPROVER, "s")
    c.execute(rid, APPROVER)
    final = c.finish(rid, "failed")
    assert final["status"] == "unresolved"
    assert c.finish(rid, "resolved")["status"] == "unresolved"
    assert "token" not in str(public(c.db.get("runs", "run#" + rid)))
    assert final["artifact"] == {"key": "immutable-investigation"}


def test_atomic_intake_failure_cannot_leave_orphan_dispatch():
    db = MemoryRepository()
    c = Control(db)
    original = db.commit

    def interrupted(changes):
        raise RuntimeError("network interrupted before commit")

    db.commit = interrupted
    request = Intake(idempotency_key="atomic", scenario="control-recovery")
    with pytest.raises(RuntimeError):
        c.intake(request, "analyst", "s")
    assert db.data == {}
    db.commit = original
    run = c.intake(request, "analyst", "s")
    assert db.get("runs", "dispatch#" + run["run_id"])["status"] == "pending"


@pytest.mark.parametrize("failure", ["before_publish", "after_publish", "exhausted"])
def test_dispatch_recovery_keeps_durable_outbox(monkeypatch, failure):
    from incident_demo.workflow import handlers

    c = Control(MemoryRepository())
    run = c.intake(Intake(idempotency_key="dispatch", scenario="control-recovery"), "a", "s")
    rid = run["run_id"]
    key = "dispatch#" + rid
    if failure == "exhausted":
        c.db.data["runs", key]["attempts"] = 3
    published, letters = [], []

    class Bus:
        def put_events(self, **kwargs):
            if failure == "before_publish":
                raise TimeoutError("before publish")
            published.append(kwargs)
            raise TimeoutError("publish accepted but response lost")

        def send_message(self, **kwargs):
            letters.append(kwargs)

    monkeypatch.setattr(handlers, "control", lambda: c)
    monkeypatch.setattr(handlers, "client", lambda _: Bus())
    monkeypatch.setenv("BUS_ARN", "bus")
    monkeypatch.setenv("DLQ_URL", "queue")
    if failure == "exhausted":
        handlers.dispatch({}, None)
        assert letters and c.db.get("runs", key)["status"] == "dead_letter"
        assert c.db.get("runs", "run#" + rid)["status"] == "failed"
    else:
        with pytest.raises(TimeoutError):
            handlers.dispatch({}, None)
        outbox = c.db.get("runs", key)
        assert outbox["status"] == "pending" and outbox["attempts"] == 1
        assert bool(published) == (failure == "after_publish")


def test_callback_recovery_after_persisted_decision(monkeypatch, ready):
    from incident_demo.workflow import handlers

    c, rid, clock = ready
    c.decide(rid, decision(c, rid), APPROVER, "s")
    delivered = []

    class States:
        def send_task_success(self, **kwargs):
            delivered.append(kwargs)

    monkeypatch.setattr(handlers, "control", lambda: c)
    monkeypatch.setattr(handlers, "client", lambda _: States())
    monkeypatch.setattr(handlers, "now", lambda: clock[0])
    handlers.recover_callbacks({}, None)
    handlers.recover_callbacks({}, None)
    assert len(delivered) == 1
    assert c.db.get("approvals", rid)["callback"] == "delivered"


def test_expired_callback_does_not_deliver_or_revive(monkeypatch, ready):
    from incident_demo.workflow import handlers

    c, rid, clock = ready
    c.decide(rid, decision(c, rid), APPROVER, "s")
    clock[0] += timedelta(minutes=16)
    monkeypatch.setattr(handlers, "control", lambda: c)
    monkeypatch.setattr(handlers, "now", lambda: clock[0])
    monkeypatch.setattr(handlers, "client", lambda _: pytest.fail("must not send expired callback"))
    handlers.recover_callbacks({}, None)
    assert c.db.get("runs", "run#" + rid)["status"] == "expired"
    with pytest.raises(Conflict):
        c.execute(rid, APPROVER)


def test_dispatch_uses_installed_sdk_contract(monkeypatch):
    from botocore.stub import Stubber

    from incident_demo.workflow import handlers

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    bus_arn = "arn:aws:events:us-east-2:498084841421:event-busv2/test/test"
    monkeypatch.setenv("BUS_ARN", bus_arn)
    c = Control(MemoryRepository())
    run = c.intake(Intake(idempotency_key="sdk", scenario="control-recovery"), "role", "s")
    monkeypatch.setattr(handlers, "control", lambda: c)
    handlers.client.cache_clear()
    try:
        with Stubber(handlers.client("eventbridgev2")) as stub:
            stub.add_response(
                "put_events",
                {"FailedEntryCount": 0, "Entries": [{"EventId": "test"}]},
                {
                    "EventBusArn": bus_arn,
                    "Entries": [
                        {
                            "Source": "incident.demo",
                            "DetailType": "IncidentAccepted",
                            "Detail": handlers.encode({"run_id": run["run_id"]}),
                        }
                    ],
                },
            )
            handlers.dispatch({}, None)
            stub.assert_no_pending_responses()
    finally:
        handlers.client.cache_clear()
