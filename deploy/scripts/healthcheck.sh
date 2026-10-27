#!/usr/bin/env bash
# Usage: healthcheck.sh [https://api-domain]   (no argument: check the local loopback endpoint)
set -euo pipefail
URL="${1:-http://127.0.0.1:8200}"
curl -fsS --max-time 10 "$URL/api/health" | python3 -m json.tool
