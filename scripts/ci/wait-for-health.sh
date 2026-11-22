#!/usr/bin/env bash
# Poll a URL until it returns HTTP 200. Render's free tier cold-starts in ~50s, so be patient.
# Usage: wait-for-health.sh <url> [max_attempts=30] [sleep_seconds=10]
set -uo pipefail
url="${1:?url required}"; max="${2:-30}"; delay="${3:-10}"
for i in $(seq 1 "$max"); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$url" || echo 000)
  echo "[$i/$max] $url -> $code"
  [[ "$code" == "200" ]] && exit 0
  sleep "$delay"
done
echo "::error::$url did not become healthy"; exit 1
