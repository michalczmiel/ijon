#!/usr/bin/env bash
# Pull events out of the session table in DynamoDB Local.
#
#   dynamodb-query.sh --session <uuid>                  every event of one session
#   dynamodb-query.sh --session <uuid> --timestamp <p>  events of that session from <p> on
#   dynamodb-query.sh --timestamp <p>                   events across all sessions from <p> on
#
# <p> is an ISO-8601 prefix, e.g. 2026-07-14 or 2026-07-14T19:21.
set -euo pipefail

ENDPOINT_URL="${ENDPOINT_URL:-http://localhost:8000}"
TABLE_NAME="${TABLE_NAME:-AgentSession}"

# DynamoDB Local ignores the values, but the CLI refuses to sign without them
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-local}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-local}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-central-1}"

session=""
timestamp=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s | --session)
      session="$2"
      shift 2
      ;;
    -t | --timestamp)
      timestamp="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$session" && -z "$timestamp" ]]; then
  echo "usage: dynamodb-query.sh [--session <uuid>] [--timestamp <iso-8601 prefix>]" >&2
  exit 1
fi

values="{}"

if [[ -n "$session" ]]; then
  # the partition key is known, so this is a key condition rather than a filter
  condition="PK = :pk"
  values=$(printf '{":pk": {"S": "%s"}}' "$session")

  if [[ -n "$timestamp" ]]; then
    condition="$condition AND begins_with(SK, :sk)"
    values=$(printf '{":pk": {"S": "%s"}, ":sk": {"S": "%s"}}' "$session" "$timestamp")
  fi

  aws dynamodb query \
    --endpoint-url "$ENDPOINT_URL" \
    --table-name "$TABLE_NAME" \
    --key-condition-expression "$condition" \
    --expression-attribute-values "$values" \
    --no-cli-pager
  exit 0
fi

# no session, so every partition has to be read and filtered after the fact
aws dynamodb scan \
  --endpoint-url "$ENDPOINT_URL" \
  --table-name "$TABLE_NAME" \
  --filter-expression "begins_with(SK, :sk)" \
  --expression-attribute-values "$(printf '{":sk": {"S": "%s"}}' "$timestamp")" \
  --no-cli-pager
