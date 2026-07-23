#!/usr/bin/env bash
# List every item in the session table in DynamoDB Local. Sessions are small here, so a
# scan is fine; against real AWS you would query by PK instead.
set -euo pipefail

ENDPOINT_URL="${ENDPOINT_URL:-http://localhost:8000}"
TABLE_NAME="${TABLE_NAME:-AgentSession}"

# DynamoDB Local ignores the values, but the CLI refuses to sign without them
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-local}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-local}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-central-1}"

aws dynamodb scan \
  --endpoint-url "$ENDPOINT_URL" \
  --table-name "$TABLE_NAME" \
  --query 'Items[].{session: PK.S, timestamp: SK.S, type: type.S}' \
  --output table \
  --no-cli-pager
