"""Exercise the real loopback HTTP boundary without AWS or model calls."""

import json
import threading
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from incident_demo.operator.cloud import CloudOperator
from incident_demo.operator.server import OperatorServer, load_examples

RUN = "p07-" + "a" * 40
DECISION = {
    "proposal_hash": "b" * 64,
    "decision": "approved",
    "reason": "Reviewed the exact evidence and synthetic scope",
    "facts_reviewed": True,
    "citations_reviewed": True,
}


@pytest.fixture
def server():
    backend = Mock()
    backend.start.return_value = (202, {"run_id": RUN, "status": "pending"})
    backend.review.return_value = (
        200,
        {"run_id": RUN, "status": "awaiting_approval", "token": "private-callback"},
    )
    backend.decide.return_value = (202, {"run_id": RUN, "decision": "approved"})
    with OperatorServer(0, backend, {}) as instance:
        thread = threading.Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        yield instance
        instance.shutdown()
        thread.join()


def request(server, path, body=None, headers=None, authenticated=True, raw=None):
    values = {"Host": server.origin.removeprefix("http://")}
    if authenticated:
        values["X-Operator-Token"] = server.token
    if body is not None or raw is not None:
        values["Content-Type"] = "application/json"
    values.update(headers or {})
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(
            "POST" if body is not None or raw is not None else "GET",
            path,
            body=raw if raw is not None else json.dumps(body) if body is not None else None,
            headers=values,
        )
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-Operator-Token": "wrong"},
    ],
)
def test_browser_boundary_rejects_foreign_requests(server, headers):
    assert request(server, "/api/incidents", {"idempotency_key": "demo-1"}, headers)[0] == 403
    server.backend.start.assert_not_called()


def test_read_api_requires_token_and_root_rejects_rebinding(server):
    assert request(server, "/api/config", authenticated=False)[0] == 403
    assert request(server, "/", headers={"Host": "attacker.test"})[0] == 403
    code, headers, data = request(server, "/", authenticated=False)
    assert code == 200 and server.token.encode() in data
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_intake_cannot_supply_scenario_role_or_target(server):
    for extra in ({"scenario": "control-recovery"}, {"role": "tester"}, {"url": "https://evil"}):
        assert request(server, "/api/incidents", {"idempotency_key": "demo-1"} | extra)[0] == 400
    assert request(server, "/api/incidents", {"idempotency_key": "demo-1"})[0] == 202
    server.backend.start.assert_called_once_with("demo-1")


@pytest.mark.parametrize(
    "body",
    [
        DECISION | {"facts_reviewed": False},
        DECISION | {"citations_reviewed": False},
        DECISION | {"reason": " "},
        DECISION | {"proposal_hash": "edited"},
        DECISION | {"actor": "admin"},
        DECISION | {"decision": "execute"},
    ],
)
def test_decision_requires_explicit_valid_review(server, body):
    assert request(server, f"/api/runs/{RUN}/decision", body)[0] == 400
    server.backend.decide.assert_not_called()


def test_decision_forwards_exact_hash_without_inventing_acknowledgments(server):
    assert request(server, f"/api/runs/{RUN}/decision", DECISION)[0] == 202
    server.backend.decide.assert_called_once_with(RUN, DECISION)


def test_review_allowlist_excludes_callback_and_routes_are_bounded(server):
    code, _, raw = request(server, f"/api/runs/{RUN}")
    assert code == 200 and b"private-callback" not in raw
    for path in ("/api/runs/../../secret", f"/api/runs/{RUN}?url=https://evil", "/.aws/config"):
        assert request(server, path)[0] == 404
    server.backend.review.assert_called_once_with(RUN)


def test_malformed_and_oversized_body(server):
    for raw in ("[1]", "bad-json", "x" * 8193):
        assert request(server, "/api/incidents", raw=raw)[0] == 400
    server.backend.start.assert_not_called()


def test_cloud_timeout_is_not_retried_or_exposed(server):
    server.backend.start.side_effect = RuntimeError("secret-session-credential")
    code, _, raw = request(server, "/api/incidents", {"idempotency_key": "demo-1"})
    assert code == 502 and b"secret" not in raw and b"outcome_unknown" in raw
    server.backend.start.assert_called_once()


def test_replay_cannot_mutate_and_retained_sources_are_labeled(server):
    server.backend = None
    assert request(server, "/api/incidents", {"idempotency_key": "demo-1"})[0] == 409
    assert request(server, f"/api/runs/{RUN}/decision", DECISION)[0] == 409
    examples = load_examples(Path(__file__).resolve().parents[1])
    assert len(examples) == 12
    assert "no model" in examples["resolved"]["provenance"]
    assert "No action" in examples["case-001"]["provenance"]
    assert "proposal" not in examples["case-001"]["run"]
    assert "token" not in examples["resolved"]["run"]


def outputs():
    return {
        "ApiUrlOutput": "https://example.execute-api.us-east-2.amazonaws.com",
        "AnalystRoleOutput": "arn:aws:iam::498084841421:role/incident-demo-p07-analyst",
        "ApproverRoleOutput": "arn:aws:iam::498084841421:role/incident-demo-p07-approver",
    }


def test_cloud_uses_expected_account_and_endpoint():
    session = Mock()
    session.client.return_value.get_caller_identity.return_value = {"Account": "wrong"}
    with pytest.raises(ValueError, match="account"):
        CloudOperator(outputs(), Mock(), session)
    session.client.return_value.get_caller_identity.return_value = {"Account": "498084841421"}
    with pytest.raises(ValueError, match="endpoint"):
        CloudOperator(outputs() | {"ApiUrlOutput": "https://evil.example"}, Mock(), session)


def test_signed_transport_and_reservation_identity(monkeypatch):
    session = Mock()
    session.client.return_value.get_caller_identity.return_value = {"Account": "498084841421"}
    reserve = Mock()
    cloud = CloudOperator(outputs(), reserve, session)
    from botocore.credentials import Credentials

    monkeypatch.setattr(cloud, "credentials", lambda role: Credentials("test", "secret", "session"))
    response = Mock()
    response.status = 202
    response.read.return_value = b'{"status":"pending"}'
    cloud.opener = Mock()
    cloud.opener.open.return_value.__enter__ = Mock(return_value=response)
    cloud.opener.open.return_value.__exit__ = Mock(return_value=False)
    cloud.start("demo-key")
    cloud.start("demo-key")
    assert reserve.call_args_list[0] == reserve.call_args_list[1]
    request = cloud.opener.open.call_args.args[0]
    assert request.full_url == outputs()["ApiUrlOutput"] + "/incidents"
    assert "AWS4-HMAC-SHA256" in request.headers["Authorization"]
    assert json.loads(request.data) == {"idempotency_key": "demo-key", "scenario": "investigate"}


def test_assumed_credentials_refresh_before_expiration(monkeypatch):
    session = Mock()
    session.client.return_value.get_caller_identity.return_value = {"Account": "498084841421"}
    cloud = CloudOperator(outputs(), Mock(), session)
    credentials = {
        "AccessKeyId": "test",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
        "Expiration": datetime.now(UTC) + timedelta(hours=1),
    }
    cloud.sts.assume_role.return_value = {"Credentials": credentials}
    monkeypatch.setattr("incident_demo.operator.cloud.boto3.Session", lambda **kwargs: Mock())
    cloud.credentials("approver")
    cloud.credentials("approver")
    assert cloud.sts.assume_role.call_count == 1
    cloud.sessions["approver"] = (datetime.now(UTC), SimpleNamespace())
    cloud.credentials("approver")
    assert cloud.sts.assume_role.call_count == 2
