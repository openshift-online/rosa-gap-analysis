#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

GAP_SCRIPTS_DIR="${GAP_SCRIPTS_DIR:-/gap-analysis/scripts}"
REPORTS_DIR="${SHARED_DIR}/gap-analysis-reports"
mkdir -p "${REPORTS_DIR}"

# OCM login so OCM/ROSA-backed data is available; degrades gracefully when no
# credentials are present. Uses the same variables and logic as
# scripts/lib/ocm_auth.sh (OCM_TOKEN, or OCM_CLIENT_ID + OCM_CLIENT_SECRET, with
# OCM_URL). Credentials come from the ci-operator mount at /var/run/ocm-credentials
# (files named after the variables); each step authenticates in its own pod.
if command -v ocm >/dev/null 2>&1; then
  # shellcheck source=/dev/null
  source "${GAP_SCRIPTS_DIR}/lib/logging.sh"
  # shellcheck source=/dev/null
  source "${GAP_SCRIPTS_DIR}/lib/ocm_auth.sh"
  ocm_load_credentials "${OCM_CREDENTIALS_DIR:-/var/run/ocm-credentials}"
  # Back-compat: honor a token staged by the ocm-auth step or the cluster profile.
  if [[ -z "${OCM_TOKEN:-}" && -f "${SHARED_DIR}/ocm-token" ]]; then
    OCM_TOKEN="$(cat "${SHARED_DIR}/ocm-token")"; export OCM_TOKEN
  elif [[ -z "${OCM_TOKEN:-}" && -n "${CLUSTER_PROFILE_DIR:-}" && -f "${CLUSTER_PROFILE_DIR}/ocm-token" ]]; then
    OCM_TOKEN="$(cat "${CLUSTER_PROFILE_DIR}/ocm-token")"; export OCM_TOKEN
  fi
  OCM_URL="${OCM_LOGIN_ENV:-staging}" ocm_authenticate || log "WARNING: OCM login failed; OCM-backed data uses graceful fallback"
fi

# Resolve versions: prefer the shared gap-versions.env, else fall back to env.
if [[ -f "${SHARED_DIR}/gap-versions.env" ]]; then
  # shellcheck source=/dev/null
  source "${SHARED_DIR}/gap-versions.env"
fi
if [[ "${GAP_SKIP:-0}" == "1" ]]; then
  log "GAP_SKIP=1 (${GAP_SKIP_REASON:-}); skipping Target E2E Validation"
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

# Optional verbose passthrough: GAP_VERBOSE=1 (set by gap-all.sh --verbose or a
# workflow's env) adds --verbose to the analyzer invocation below.
if [[ "${GAP_VERBOSE:-0}" == "1" ]]; then
  version_args+=(--verbose)
fi

log "Running gap-e2e-validation.py ${version_args[*]}"
rc=0
python3 "${GAP_SCRIPTS_DIR}/gap-e2e-validation.py" "${version_args[@]}" --report-dir "${REPORTS_DIR}" || rc=$?

# Surface reports as artifacts even if the check failed.
cp -r "${REPORTS_DIR}/." "${ARTIFACT_DIR}/" 2>/dev/null || true

exit "${rc}"
