#!/usr/bin/env bash
# Vendor ijon.py into the Lambda asset directory. Runs before every synth so the
# deployed bundle and the local invoke always carry the same harness.
set -euo pipefail

IJON_URL="${IJON_URL:-https://raw.githubusercontent.com/michalczmiel/ijon/main/python/ijon.py}"
DESTINATION="$(dirname "$0")/../src/agent-runner/ijon.py"

curl -fsSL -o "$DESTINATION" "$IJON_URL"

echo "fetched $IJON_URL -> ${DESTINATION#*/../}"
