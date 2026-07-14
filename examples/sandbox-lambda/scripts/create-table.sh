#!/usr/bin/env bash
# Create the session table in DynamoDB Local (compose.yml). CDK never touches it, so it
# has to be created once by hand; the compose volume keeps it around afterwards.
set -euo pipefail

ENDPOINT_URL="${ENDPOINT_URL:-http://localhost:8000}"
TABLE_NAME="${TABLE_NAME:-AgentSession}"

# DynamoDB Local ignores the values, but the CLI refuses to sign without them
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-local}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-local}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-central-1}"

if aws dynamodb describe-table \
  --endpoint-url "$ENDPOINT_URL" \
  --table-name "$TABLE_NAME" >/dev/null 2>&1; then
  echo "table $TABLE_NAME already exists"
  exit 0
fi

aws dynamodb create-table \
  --endpoint-url "$ENDPOINT_URL" \
  --table-name "$TABLE_NAME" \
  --attribute-definitions \
    AttributeName=PK,AttributeType=S \
    AttributeName=SK,AttributeType=S \
  --key-schema \
    AttributeName=PK,KeyType=HASH \
    AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --no-cli-pager

echo "created table $TABLE_NAME"
