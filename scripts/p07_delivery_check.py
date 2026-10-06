"""Bounded live failure test: malformed synthetic event must reach the owned DLQ."""

import json
import time
from pathlib import Path
from uuid import uuid4

from p07_workflow import CONFIG, Operator


def main():
    op = Operator()
    marker = "p07-delivery-test-" + uuid4().hex
    # Matches the subscriber but deliberately lacks a run_id. Cannot create a request or action.
    response = op.sdk.client("eventbridgev2", config=CONFIG).put_events(
        EventBusArn=op.outputs["BusArnOutput"],
        Entries=[
            {
                "Source": "incident.demo",
                "DetailType": "IncidentAccepted",
                "Detail": json.dumps({"control_test": marker}),
            }
        ],
    )
    if response.get("FailedEntryCount", 0):
        raise RuntimeError("test publish failed")
    event_id = response["Entries"][0]["EventId"]
    folder = Path(__file__).resolve().parents[1] / "docs/evidence/p07"
    (folder / (marker + "-publish.json")).write_text(
        json.dumps({"marker": marker, "event_id": event_id}, indent=2) + "\n"
    )
    sqs = op.sdk.client("sqs", config=CONFIG)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        reply = sqs.receive_message(
            QueueUrl=op.outputs["DeadLetterUrlOutput"],
            MaxNumberOfMessages=10,
            WaitTimeSeconds=10,
            VisibilityTimeout=15,
        )
        for message in reply.get("Messages", []):
            body = json.loads(message["Body"])
            # EventsV2 failure records contain event IDs, not the original payload.
            if not any(m.get("eventId") == event_id for m in body.get("failedMessages", [])):
                continue  # Never remove another run's dead letter.
            evidence = {
                "passed": True,
                "marker": marker,
                "event_id": event_id,
                "message_id": message["MessageId"],
                "body": body,
                "publish_request_id": response["ResponseMetadata"]["RequestId"],
            }
            target = folder / "delivery-dlq.json"
            target.write_text(json.dumps(evidence, indent=2) + "\n")
            sqs.delete_message(
                QueueUrl=op.outputs["DeadLetterUrlOutput"], ReceiptHandle=message["ReceiptHandle"]
            )
            print(json.dumps({"passed": True, "test_message_retained_then_removed": marker}))
            return
    raise TimeoutError("failed event did not reach DLQ within 180 seconds")


if __name__ == "__main__":
    main()
