#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

GAP_SCRIPTS_DIR="${GAP_SCRIPTS_DIR:-/gap-analysis/scripts}"
REPORTS_DIR="${SHARED_DIR}/gap-analysis-reports"
mkdir -p "${REPORTS_DIR}"

# Optional OCM login (version gates / marketplace checks); degrades gracefully.
# Prefer the token the rosa-gap-analysis-ocm-auth step staged, then the cluster profile.
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
      log "WARNING: OCM login failed; GA readiness validation will use graceful fallback"
    fi
  else
    log "No OCM token available; GA readiness OCM data uses graceful fallback"
  fi
fi

# Resolve versions: prefer the shared gap-versions.env, else fall back to env.
if [[ -f "${SHARED_DIR}/gap-versions.env" ]]; then
  # shellcheck source=/dev/null
  source "${SHARED_DIR}/gap-versions.env"
fi
if [[ "${GAP_SKIP:-0}" == "1" ]]; then
  log "GAP_SKIP=1 (${GAP_SKIP_REASON:-}); skipping GA readiness validation"
  exit 0
fi

version_args=()
if [[ -n "${BASELINE:-}" && -n "${TARGET:-}" ]]; then
  version_args=(--baseline "${BASELINE}" --target "${TARGET}")
elif [[ -n "${OPENSHIFT_VERSION:-}" ]]; then
  version_args=(--version "${OPENSHIFT_VERSION}")
else
  log "ERROR: no version input; set OPENSHIFT_VERSION (or BASELINE+TARGET), or run rosa-gap-analysis-resolve-versions first"
  exit 1
fi

log "Running prod/gap-ga-validation.py ${version_args[*]}"
rc=0
python3 "${GAP_SCRIPTS_DIR}/prod/gap-ga-validation.py" "${version_args[@]}" --report-dir "${REPORTS_DIR}" || rc=$?

# Surface the GA-readiness report as artifacts even if validation failed.
cp -r "${REPORTS_DIR}/." "${ARTIFACT_DIR}/" 2>/dev/null || true

exit "${rc}"
