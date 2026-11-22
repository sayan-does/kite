#!/usr/bin/env bash
# Black-box API smoke test against a deployed backend. Read-only, no auth required.
# Usage: api-smoke.sh <api-base-url> [allowed-origin-for-cors-check]
set -uo pipefail
base="${1:?api base url required}"; base="${base%/}"; origin="${2:-}"
fail=0
check() { # name expected_status curl-args...
  local name="$1" want="$2"; shift 2
  local got; got=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$@")
  if [[ "$got" == "$want" ]]; then echo "PASS  $name ($got)"; else echo "FAIL  $name: expected $want, got $got"; fail=1; fi
}
check "health"                          200 "$base/health"
check "internal trigger rejects no key" 401 -X POST "$base/internal/run-daily"
check "protected route needs auth"      401 "$base/me"
if [[ -n "$origin" ]]; then
  hdr=$(curl -s -D - -o /dev/null --max-time 60 -X OPTIONS -H "Origin: $origin" -H "Access-Control-Request-Method: GET" "$base/health" | tr -d '\r' | grep -i '^access-control-allow-origin' || true)
  if [[ "$hdr" == *"$origin"* ]]; then echo "PASS  CORS allows $origin"; else echo "FAIL  CORS does not allow $origin"; fail=1; fi
fi
exit $fail
