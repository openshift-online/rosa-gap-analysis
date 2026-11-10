#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

GAP_SCRIPTS_DIR="${GAP_SCRIPTS_DIR:-/gap-analysis/scripts}"
REPORTS_DIR="${SHARED_DIR}/gap-analysis-reports"
mkdir -p "${REPORTS_DIR}"

if [[ -f "${SHARED_DIR}/gap-versions.env" ]]; then
  # shellcheck source=/dev/null
  source "${SHARED_DIR}/gap-versions.env"
fi
if [[ "${GAP_SKIP:-0}" == "1" ]]; then
  log "GAP_SKIP=1 (${GAP_SKIP_REASON:-}); no combined report to generate"
  exit 0
fi

if [[ -z "${BASELINE:-}" || -z "${TARGET:-}" ]]; then
  log "ERROR: no resolved versions (run rosa-gap-analysis-resolve-versions or set BASELINE+TARGET)"
  exit 1
fi

log "Generating combined report for ${BASELINE} -> ${TARGET}"
combined_rc=0
python3 "${GAP_SCRIPTS_DIR}/generate-combined-report.py" \
  --baseline "${BASELINE}" \
  --target "${TARGET}" \
  --report-dir "${REPORTS_DIR}" || combined_rc=$?

if [[ ${combined_rc} -ne 0 ]]; then
  log "WARNING: combined report generation failed (rc=${combined_rc}); individual reports are still available"
fi

# Surface all reports (per-check + combined) as artifacts.
cp -r "${REPORTS_DIR}/." "${ARTIFACT_DIR}/" 2>/dev/null || true

# The job verdict is owned by the individual check steps, not by report generation.
exit 0
