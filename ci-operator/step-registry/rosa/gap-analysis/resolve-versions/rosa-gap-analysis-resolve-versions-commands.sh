#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

GAP_SCRIPTS_DIR="${GAP_SCRIPTS_DIR:-/gap-analysis/scripts}"
# shellcheck source=/dev/null
source "${GAP_SCRIPTS_DIR}/lib/logging.sh"
# shellcheck source=/dev/null
source "${GAP_SCRIPTS_DIR}/lib/openshift-releases.sh"

RUN_ENV="${SHARED_DIR}/gap-versions.env"

num_dots() { echo "${1}" | tr -cd '.' | wc -c; }

write_skip() {
  log "resolve-versions: ${1} -> GAP_SKIP=1 (workflow will skip gap analysis)"
  {
    printf 'GAP_SKIP=1\n'
    printf 'GAP_SKIP_REASON=%q\n' "${1}"
  } > "${RUN_ENV}"
  exit 0
}

baseline=""
target=""

if [[ -n "${OPENSHIFT_VERSION:-}" ]]; then
  log "Resolving BASELINE and TARGET from OPENSHIFT_VERSION=${OPENSHIFT_VERSION}"
  rc=0
  result="$(resolve_openshift_version "${OPENSHIFT_VERSION}")" || rc=$?
  if [[ ${rc} -ne 0 ]]; then
    write_skip "version ${OPENSHIFT_VERSION} not found in accepted streams or not available"
  fi
  if [[ "${result}" == "SKIP SKIP" ]]; then
    write_skip "only one z-stream version available for ${OPENSHIFT_VERSION}"
  fi
  baseline="$(echo "${result}" | awk '{print $1}')"
  target="$(echo "${result}" | awk '{print $2}')"

elif [[ -n "${BASELINE:-}" && -n "${TARGET:-}" ]]; then
  baseline="${BASELINE}"
  target="${TARGET}"
  if [[ "$(num_dots "${baseline}")" -eq 1 ]]; then
    baseline="$(get_latest_version_baseline_priority "${baseline}")"
  fi
  if [[ "$(num_dots "${target}")" -eq 1 ]]; then
    target="$(get_latest_version_target_priority "${target}")"
  fi

else
  log "Auto-detecting BASELINE (latest stable) and TARGET (latest candidate)"
  baseline="$(get_latest_stable_version)"
  baseline_minor="$(extract_version_from_stable "${baseline}")"
  special_target="$(get_special_target_mapping "${baseline_minor}" || true)"
  if [[ -n "${special_target}" ]]; then
    log "Applying special target mapping: ${baseline_minor} -> ${special_target}"
    target="$(get_latest_version_target_priority "${special_target}")"
  else
    target="$(get_latest_candidate_version)"
  fi
fi

if [[ -z "${baseline}" || -z "${target}" ]]; then
  log "ERROR: failed to resolve baseline/target (baseline='${baseline}' target='${target}')"
  exit 1
fi

# printf %q keeps the file safe to `source` even if a version contains metacharacters.
{
  printf 'GAP_SKIP=0\n'
  printf 'BASELINE=%q\n' "${baseline}"
  printf 'TARGET=%q\n' "${target}"
} > "${RUN_ENV}"

log "Resolved BASELINE=${baseline} TARGET=${target} -> ${RUN_ENV}"
