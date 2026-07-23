import datetime
import json
import os
import subprocess
import sys
import uuid

import boto3

# ijon.py is vendored next to this file by scripts/fetch-ijon.sh
IJON = os.path.join(os.path.dirname(__file__), "ijon.py")

# the endpoint is set only when pointed at DynamoDB Local, empty means real AWS
dynamodb = boto3.resource(
    "dynamodb", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_DYNAMODB") or None
)
table = dynamodb.Table(os.environ["AGENT_SESSION_TABLE_NAME"])


def store_event(batch, session_id: str, event: dict) -> None:
    batch.put_item(
        Item={
            "PK": session_id,
            # fixed-width UTC: microseconds are always padded, so the sort key
            # sorts lexicographically in event order
            "SK": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "type": event["type"],
            # events carry floats and empty strings, which DynamoDB rejects
            "event": json.dumps(event),
        }
    )


def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    session_id = str(uuid.uuid4())

    # ijon streams JSONL on stdout and logs the agent loop on stderr; stderr is
    # inherited so it lands in CloudWatch as the session runs
    process = subprocess.Popen(
        [
            sys.executable,
            IJON,
            body["prompt"],
            "--model",
            body["model"],
            "--bash",
            "--jsonl",
        ],
        stdout=subprocess.PIPE,
        text=True,
        # /tmp is the only writable path, so that is where the bash tool works
        cwd="/tmp",
    )

    # timestamp each event as it arrives, so the sort key is the session timeline;
    # the Lambda timeout is the backstop if the agent never finishes
    count = 0
    with table.batch_writer() as batch:
        for line in process.stdout:
            if not line.strip():
                continue
            store_event(batch, session_id, json.loads(line))
            count += 1

    returncode = process.wait()

    return {
        "statusCode": 200 if returncode == 0 else 500,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"session_id": session_id, "events": count}),
    }
