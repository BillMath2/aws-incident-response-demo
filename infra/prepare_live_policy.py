"""Validate and install the reviewed, project-scoped P05 deployment policy."""

import json
import subprocess
from pathlib import Path

from live_deployment_policy import monitoring_policy, policy
from manage import aws, verify_identity
from settings import load_config


def install(config, document, name, filename):
    folder = Path(__file__).resolve().parents[1] / "docs/evidence/p05"
    folder.mkdir(exist_ok=True)
    validation = aws(
        config,
        "accessanalyzer",
        "validate-policy",
        "--policy-type",
        "IDENTITY_POLICY",
        "--policy-document",
        json.dumps(document),
    )
    if validation["findings"]:
        raise RuntimeError(json.dumps(validation["findings"]))
    arn = f"arn:aws:iam::{config['account']}:policy/{name}"
    try:
        existing = aws(config, "iam", "get-policy", "--policy-arn", arn)["Policy"]
    except subprocess.CalledProcessError as exc:
        if "NoSuchEntity" not in exc.stderr:
            raise
        aws(
            config,
            "iam",
            "create-policy",
            "--policy-name",
            name,
            "--policy-document",
            json.dumps(document),
            "--tags",
            "Key=Project,Value=incident-demo",
        )
    else:
        current = aws(
            config,
            "iam",
            "get-policy-version",
            "--policy-arn",
            arn,
            "--version-id",
            existing["DefaultVersionId"],
        )["PolicyVersion"]["Document"]
        if current != document:
            retained = folder / f"{filename}.json"
            if not retained.exists() or json.loads(retained.read_text()) != current:
                raise ValueError("Existing policy is not the previously retained project policy")
            (folder / f"{filename}-{existing['DefaultVersionId']}.json").write_text(
                json.dumps(current, indent=2) + "\n"
            )
            versions = aws(config, "iam", "list-policy-versions", "--policy-arn", arn)["Versions"]
            if len(versions) >= 5:
                oldest = sorted(
                    (v for v in versions if not v["IsDefaultVersion"]),
                    key=lambda v: v["CreateDate"],
                )[0]
                version = oldest["VersionId"]
                archived = folder / f"{filename}-{version}.json"
                original = aws(
                    config,
                    "iam",
                    "get-policy-version",
                    "--policy-arn",
                    arn,
                    "--version-id",
                    version,
                )["PolicyVersion"]
                if (
                    original["IsDefaultVersion"]
                    or not archived.exists()
                    or json.loads(archived.read_text()) != original["Document"]
                ):
                    raise ValueError("Cannot prune an unverified or current policy version")
                # IAM retains at most five versions. Only the oldest non-default,
                # exact locally archived project version may make room for an update.
                aws(
                    config,
                    "iam",
                    "delete-policy-version",
                    "--policy-arn",
                    arn,
                    "--version-id",
                    version,
                )
            aws(
                config,
                "iam",
                "create-policy-version",
                "--policy-arn",
                arn,
                "--policy-document",
                json.dumps(document),
                "--set-as-default",
            )
    aws(
        config,
        "iam",
        "attach-role-policy",
        "--policy-arn",
        arn,
        "--role-name",
        f"cdk-incdemo-cfn-exec-role-{config['account']}-{config['region']}",
    )
    (folder / f"{filename}.json").write_text(json.dumps(document, indent=2) + "\n")
    (folder / f"{filename}-validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    print("Validated P05 execution policy attached to the project bootstrap execution role.")


def main():
    config = load_config()
    verify_identity(config)
    install(config, policy(config), "incident-demo-p05-cfn-execution", "cfn-execution-policy")
    install(
        config,
        monitoring_policy(config),
        "incident-demo-p05-monitoring-execution",
        "monitoring-execution-policy",
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr) from None
