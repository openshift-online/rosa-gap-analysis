#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

log "[setup] Validating prerequisites..."
missing=0
for cmd in python3 jq; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log "[setup] ERROR: required command not found: ${cmd}"
    missing=1
  fi
done
if [[ "${missing}" -ne 0 ]]; then
  log "[setup] Missing required tooling; cannot continue."
  exit 1
fi
for cmd in oc ocm rosa gcloud; do
  command -v "${cmd}" >/dev/null 2>&1 || log "[setup] Optional command not found: ${cmd} (dependent checks degrade/SKIP)"
done

REPORTS_DIR="${SHARED_DIR}/gap-analysis-reports"
log "[setup] Initializing ${REPORTS_DIR}"
mkdir -p "${REPORTS_DIR}"
# Clear stale per-run state so a reused SHARED_DIR cannot surface previous data.
rm -f "${REPORTS_DIR}"/status-check-*.json "${REPORTS_DIR}"/result-check-*.rc 2>/dev/null || true
rm -f "${SHARED_DIR}/gap-versions.env" 2>/dev/null || true

log "[setup] Environment ready."
