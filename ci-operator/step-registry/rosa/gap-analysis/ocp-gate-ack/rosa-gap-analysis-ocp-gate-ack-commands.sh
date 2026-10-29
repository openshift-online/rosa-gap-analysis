#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

GAP_SCRIPTS_DIR="${GAP_SCRIPTS_DIR:-/gap-analysis/scripts}"
REPORTS_DIR="${SHARED_DIR}/gap-analysis-reports"
mkdir -p "${REPORTS_DIR}"

# Optional OCM login so OCM/ROSA-backed data is available; degrades gracefully.
# Prefer the token the rosa-gap-analysis-ocm-auth step wrote to SHARED_DIR, then
# fall back to the cluster profile (each ci-operator step runs in its own pod, so
# the login itself cannot be shared - only the token can).
if command -v ocm >/dev/null 2>&1; then
  ocm_token=""
  if [[ -f "${SHARED_DIR}/ocm-token" ]]; then
    ocm_token="$(cat "${SHARED_DIR}/ocm-token" 2>/dev/null || true)"
  elif [[ -n "${CLUSTER_PROFILE_DIR:-}" && -f "${CLUSTER_PROFILE_DIR}/ocm-token" ]]; then
    ocm_token="$(cat "${CLUSTER_PROFILE_DIR}/ocm-token" 2>/dev/null || true)"
  fi
  if [[ -n "${ocm_token}" ]]; then
    if ocm login --url "${OCM_LOGIN_ENV:-staging}" --token "${ocm_token}" >/dev/null 2>&1; then
      log "Logged into OCM (${OCM_LOGIN_ENV:-staging})"
    else
      log "WARNING: OCM login failed; OCP Admin Gate Acknowledgments will use graceful fallback"
    fi
  else
    log "No OCM token available; OCP Admin Gate Acknowledgments OCM data uses graceful fallback"
  fi
fi

# Resolve versions: prefer the shared gap-versions.env, else fall back to env.
if [[ -f "${SHARED_DIR}/gap-versions.env" ]]; then
  # shellcheck source=/dev/null
  source "${SHARED_DIR}/gap-versions.env"
fi
if [[ "${GAP_SKIP:-0}" == "1" ]]; then
  log "GAP_SKIP=1 (${GAP_SKIP_REASON:-}); skipping OCP Admin Gate Acknowledgments"
  exit 0
fi

version_args=()
if [[ -n "${BASELINE:-}" && -n "${TARGET:-}" ]]; then
  version_args=(--baseline "${BASELINE}" --target "${TARGET}")
elif [[ -n "${OPENSHIFT_VERSION:-}" ]]; then
  version_args=(--version "${OPENSHIFT_VERSION}")
else
  log "ERROR: no version input; run rosa-gap-analysis-resolve-versions first or set OPENSHIFT_VERSION (or BASELINE+TARGET)"
  exit 1
fi

log "Running gap-ocp-gate-ack.py ${version_args[*]}"
rc=0
python3 "${GAP_SCRIPTS_DIR}/gap-ocp-gate-ack.py" "${version_args[@]}" --report-dir "${REPORTS_DIR}" || rc=$?

# Surface reports as artifacts even if the check failed.
cp -r "${REPORTS_DIR}/." "${ARTIFACT_DIR}/" 2>/dev/null || true

exit "${rc}"
