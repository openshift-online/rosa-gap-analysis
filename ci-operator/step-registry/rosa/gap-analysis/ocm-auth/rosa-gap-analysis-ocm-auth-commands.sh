#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

if ! command -v ocm >/dev/null 2>&1; then
  log "[ocm-auth] ocm CLI not present in image; skipping (OCM-backed checks degrade gracefully)"
  exit 0
fi

ocm_token=""
if [[ -n "${CLUSTER_PROFILE_DIR:-}" && -f "${CLUSTER_PROFILE_DIR}/ocm-token" ]]; then
  ocm_token="$(cat "${CLUSTER_PROFILE_DIR}/ocm-token" 2>/dev/null || true)"
fi

if [[ -z "${ocm_token}" ]]; then
  log "[ocm-auth] No OCM token in CLUSTER_PROFILE_DIR; continuing without OCM auth (checks degrade gracefully)"
  exit 0
fi

log "[ocm-auth] Validating OCM token against ${OCM_LOGIN_ENV:-staging}..."
if ocm login --url "${OCM_LOGIN_ENV:-staging}" --token "${ocm_token}" >/dev/null 2>&1; then
  # Stage the token for downstream steps (each runs in its own pod).
  printf '%s' "${ocm_token}" > "${SHARED_DIR}/ocm-token"
  chmod 600 "${SHARED_DIR}/ocm-token" 2>/dev/null || true
  log "[ocm-auth] OCM token valid; staged at \${SHARED_DIR}/ocm-token for downstream checks."
else
  log "[ocm-auth] WARNING: OCM login failed; OCM-backed checks will degrade gracefully"
fi
