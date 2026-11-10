#!/bin/bash

set -o nounset
set -o errexit
set -o pipefail

log() { echo -e "\033[1m$(date "+%d-%m-%YT%H:%M:%S") ${*}\033[0m" >&2; }

log "[cleanup] Removing staged secrets/scratch from SHARED_DIR..."
rm -f "${SHARED_DIR}/ocm-token" "${SHARED_DIR}/gap-versions.env" 2>/dev/null || true

log "[cleanup] Removing analyzer temp directories..."
tmp_root="${TMPDIR:-/tmp}"; tmp_root="${tmp_root%/}"
removed=0
for pattern in "ocp-crs-" "mcc-checkout-"; do
  for dir in "${tmp_root}/${pattern}"*; do
    if [[ -d "${dir}" ]]; then
      rm -rf "${dir}" 2>/dev/null && removed=$((removed + 1)) || true
    fi
  done
done

log "[cleanup] Done (removed ${removed} temp dir(s))."
exit 0
