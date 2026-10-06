"""Role credentials only in AWS; disable hidden SDK retries."""

import boto3
from botocore.config import Config

REGION = "us-east-2"


def sdk_config(timeout=15):
    return Config(
        region_name=REGION,
        connect_timeout=2,
        read_timeout=max(0.1, min(timeout, 30)),
        retries={"total_max_attempts": 1, "mode": "standard"},
    )


def session():
    return boto3.Session(region_name=REGION)
