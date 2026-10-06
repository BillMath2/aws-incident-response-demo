"""CDK entry point with account checks and an explicit region on every live command."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from settings import ROOT, load_config


def aws(config: dict, *args: str) -> dict:
    executable = shutil.which("aws")
    if not executable:
        raise RuntimeError("AWS CLI v2 must be on PATH")
    command = [
        executable,
        *args,
        "--profile",
        config["profile"],
        "--region",
        config["region"],
        "--output",
        "json",
        "--no-cli-pager",
        "--cli-connect-timeout",
        "10",
        "--cli-read-timeout",
        "30",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=90)
    return json.loads(result.stdout or "{}")


def verify_identity(config: dict) -> dict:
    identity = aws(config, "sts", "get-caller-identity")
    if identity["Account"] != config["account"]:
        raise RuntimeError("credential account differs from infra/config.json; refusing operation")
    return {"account": identity["Account"], "region": config["region"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["synth", "diff", "deploy", "bootstrap", "identity"])
    args = parser.parse_args()
    config = load_config()
    if args.action != "synth":
        print(json.dumps(verify_identity(config)), flush=True)
    if args.action == "identity":
        return
    env = os.environ.copy()
    env["JSII_RUNTIME_PACKAGE_CACHE_ROOT"] = str(ROOT.parent / ".tools/jsii")
    env["AWS_REGION"] = config["region"]
    env["AWS_DEFAULT_REGION"] = config["region"]
    env["AWS_PROFILE"] = config["profile"]
    env["CDK_DISABLE_VERSION_CHECK"] = "1"
    env["AWS_MAX_ATTEMPTS"] = "1"
    node = shutil.which("node")
    cdk = ROOT / "node_modules/aws-cdk/bin/cdk"
    if not node or not cdk.exists():
        raise RuntimeError("run npm ci in infra first; Node.js is required")
    command = [node, str(cdk), args.action, "--app", f'"{Path(sys.executable)}" app.py']
    if args.action == "bootstrap":
        execution_policy = f"arn:aws:iam::{config['account']}:policy/incident-demo-cfn-execution"
        command += [
            f"aws://{config['account']}/{config['region']}",
            "--qualifier",
            config["bootstrap_qualifier"],
            "--toolkit-stack-name",
            "incident-demo-toolkit",
            "--cloudformation-execution-policies",
            execution_policy,
            "--termination-protection",
            "--tags",
            "Project=incident-demo",
        ]
    else:
        command += [config["stack_name"]]
        command += ["--no-lookups", "--strict"]
        if args.action == "diff":
            command += ["--no-change-set"]
        if args.action == "deploy":
            command += ["--require-approval", "never", "--outputs-file", "cdk.out/outputs.json"]
    command += ["--profile", config["profile"], "--no-notices"]
    subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
