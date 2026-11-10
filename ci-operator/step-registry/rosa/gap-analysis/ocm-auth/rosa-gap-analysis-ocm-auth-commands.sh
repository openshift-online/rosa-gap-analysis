#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

GAP_SCRIPTS_DIR="${GAP_SCRIPTS_DIR:-/gap-analysis/scripts}"

if ! command -v ocm >/dev/null 2>&1; then
  log "[ocm-auth] ocm CLI not present in image; skipping (OCM-backed checks degrade gracefully)"
  exit 0
fi

# shellcheck source=/dev/null
source "${GAP_SCRIPTS_DIR}/lib/logging.sh"
# shellcheck source=/dev/null
source "${GAP_SCRIPTS_DIR}/lib/ocm_auth.sh"

# Load credentials the same way scripts/lib/ocm_auth.sh expects: OCM_TOKEN, or
# OCM_CLIENT_ID + OCM_CLIENT_SECRET, from the ci-operator mount at
# /var/run/ocm-credentials (files named after the variables).
ocm_load_credentials "${OCM_CREDENTIALS_DIR:-/var/run/ocm-credentials}"
# Back-compat: a token from the cluster profile.
if [[ -z "${OCM_TOKEN:-}" && -n "${CLUSTER_PROFILE_DIR:-}" && -f "${CLUSTER_PROFILE_DIR}/ocm-token" ]]; then
  OCM_TOKEN="$(cat "${CLUSTER_PROFILE_DIR}/ocm-token")"
  export OCM_TOKEN
fi

if [[ -z "${OCM_TOKEN:-}" && ( -z "${OCM_CLIENT_ID:-}" || -z "${OCM_CLIENT_SECRET:-}" ) ]]; then
  log "[ocm-auth] No OCM credentials (OCM_TOKEN or OCM_CLIENT_ID+OCM_CLIENT_SECRET); continuing without OCM auth (checks degrade gracefully)"
  exit 0
fi

# ocm_authenticate consumes OCM_URL; keep a copy of any explicit token first.
staged_token="${OCM_TOKEN:-}"

log "[ocm-auth] Validating OCM login against ${OCM_LOGIN_ENV:-staging}..."
if OCM_URL="${OCM_LOGIN_ENV:-staging}" ocm_authenticate; then
  log "[ocm-auth] OCM login OK."
  # Each downstream check authenticates itself from the same credential mount,
  # but stage an explicit token (if one was provided) for back-compat.
  if [[ -n "${staged_token}" ]]; then
    printf '%s' "${staged_token}" > "${SHARED_DIR}/ocm-token"
    chmod 600 "${SHARED_DIR}/ocm-token" 2>/dev/null || true
    log "[ocm-auth] Staged OCM token at \${SHARED_DIR}/ocm-token for downstream checks."
  fi
else
  log "[ocm-auth] WARNING: OCM login failed; OCM-backed checks will degrade gracefully"
fi
