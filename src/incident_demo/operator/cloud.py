"""Narrow signed API client. Temporary AWS credentials never reach the browser."""

import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config

ACCOUNT = "498084841421"
REGION = "us-east-2"
CONFIG = Config(connect_timeout=5, read_timeout=15, retries={"total_max_attempts": 1})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CloudOperator:
    def __init__(self, outputs, reserve, session=None):
        self.outputs, self.reserve = outputs, reserve
        self.sdk = session or boto3.Session(profile_name="incident-demo", region_name=REGION)
        self.sts = self.sdk.client("sts", config=CONFIG)
        if self.sts.get_caller_identity()["Account"] != ACCOUNT:
            raise ValueError("Wrong AWS account")
        if not re.fullmatch(
            r"https://[a-z0-9]+\.execute-api\.us-east-2\.amazonaws\.com",
            outputs["ApiUrlOutput"],
        ):
            raise ValueError("Unexpected API endpoint")
        for role in ("Analyst", "Approver"):
            if outputs[role + "RoleOutput"] != (
                f"arn:aws:iam::{ACCOUNT}:role/incident-demo-p07-{role.lower()}"
            ):
                raise ValueError("Unexpected operator role")
        self.sessions = {}
        self.opener = build_opener(NoRedirect())

    def credentials(self, role):
        previous = self.sessions.get(role)
        if not previous or previous[0] <= datetime.now(UTC) + timedelta(minutes=5):
            result = self.sts.assume_role(
                RoleArn=self.outputs[role.title() + "RoleOutput"],
                RoleSessionName="p09-local-operator",
                DurationSeconds=3600,
            )["Credentials"]
            session = boto3.Session(
                region_name=REGION,
                aws_access_key_id=result["AccessKeyId"],
                aws_secret_access_key=result["SecretAccessKey"],
                aws_session_token=result["SessionToken"],
            )
            self.sessions[role] = result["Expiration"], session
        return self.sessions[role][1].get_credentials().get_frozen_credentials()

    def api(self, role, method, path, body=None):
        url = self.outputs["ApiUrlOutput"] + path
        data = json.dumps(body).encode() if body is not None else None
        signed = AWSRequest(
            method=method, url=url, data=data, headers={"content-type": "application/json"}
        )
        SigV4Auth(self.credentials(role), "execute-api", REGION).add_auth(signed)
        request = Request(url, data=data, headers=dict(signed.headers), method=method)
        try:
            with self.opener.open(request, timeout=20) as reply:
                raw = reply.read(262145)
                if len(raw) > 262144:
                    raise ValueError("API response too large")
                return reply.status, json.loads(raw)
        except HTTPError as exc:
            # Do not forward upstream bodies, redirects or authentication details.
            with exc:
                return exc.code, {"error": "cloud_request_rejected"}

    def start(self, key):
        run_id = (
            "p07-"
            + sha256((self.outputs["AnalystRoleOutput"] + ":" + key).encode()).hexdigest()[:40]
        )
        self.reserve(run_id)
        return self.api(
            "analyst", "POST", "/incidents", {"idempotency_key": key, "scenario": "investigate"}
        )

    def review(self, run_id):
        return self.api("approver", "GET", f"/runs/{run_id}?review=true")

    def decide(self, run_id, decision):
        return self.api("approver", "POST", f"/runs/{run_id}/decision", decision)
