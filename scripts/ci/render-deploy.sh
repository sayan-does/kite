#!/usr/bin/env bash
# Trigger a Render deploy for a service, wait until it is live, then health-check it.
# Usage: render-deploy.sh deploy   -> triggers + waits (prints previous live deploy id to $GITHUB_OUTPUT)
#        render-deploy.sh rollback <deploy-id>
# Env: RENDER_API_KEY, RENDER_SERVICE_ID, API_URL (public base URL for the health check)
set -euo pipefail

: "${RENDER_API_KEY:?RENDER_API_KEY is required}"
: "${RENDER_SERVICE_ID:?RENDER_SERVICE_ID is required}"
API="https://api.render.com/v1/services/${RENDER_SERVICE_ID}"
AUTH=(-H "Authorization: Bearer ${RENDER_API_KEY}" -H "Accept: application/json" -H "Content-Type: application/json")
TERMINAL_BAD="build_failed update_failed canceled deactivated pre_deploy_failed"

wait_for_deploy() {
  local id="$1" status
  for _ in $(seq 1 80); do # ~20 min
    status=$(curl -fsS "${AUTH[@]}" "${API}/deploys/${id}" | jq -r .status)
    echo "deploy ${id}: ${status}"
    [[ "$status" == "live" ]] && return 0
    for bad in $TERMINAL_BAD; do [[ "$status" == "$bad" ]] && { echo "::error::Render deploy ended as ${status}"; return 1; }; done
    sleep 15
  done
  echo "::error::Timed out waiting for Render deploy"; return 1
}

case "${1:-deploy}" in
  deploy)
    prev=$(curl -fsS "${AUTH[@]}" "${API}/deploys?limit=20" | jq -r '[.[].deploy | select(.status=="live")][0].id // empty')
    [[ -n "${GITHUB_OUTPUT:-}" ]] && echo "previous_deploy_id=${prev}" >> "$GITHUB_OUTPUT"
    new=$(curl -fsS -X POST "${AUTH[@]}" -d '{"clearCache":"do_not_clear"}' "${API}/deploys" | jq -r .id)
    echo "triggered deploy ${new} (previous live: ${prev:-none})"
    wait_for_deploy "$new"
    "$(dirname "$0")/wait-for-health.sh" "${API_URL:?API_URL is required}/health"
    ;;
  rollback)
    id="${2:?deploy id required}"
    echo "rolling back to ${id}"
    curl -fsS -X POST "${AUTH[@]}" -d "{\"deployId\":\"${id}\"}" "${API}/rollback" >/dev/null
    sleep 10
    "$(dirname "$0")/wait-for-health.sh" "${API_URL:?API_URL is required}/health"
    ;;
  *) echo "unknown command"; exit 2 ;;
esac
