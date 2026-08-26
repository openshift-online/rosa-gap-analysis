#!/usr/bin/env bash
# Local fallback for `make lint` when ruff/shellcheck are not on PATH.
# The Prow image already pins them in ci/Containerfile; this is a no-op there.

set -euo pipefail

PYTHON="${PYTHON:-python3}"
export PIP_DISABLE_PIP_VERSION_CHECK=1

USER_BASE="$("${PYTHON}" -m site --user-base 2>/dev/null || true)"
if [[ -n "${USER_BASE}" ]]; then
    export PATH="${USER_BASE}/bin:${PATH}"
fi

if ! command -v ruff >/dev/null 2>&1; then
    echo "==> installing ruff"
    "${PYTHON}" -m pip install --user --quiet 'ruff==0.12.11'
fi

if ! command -v shellcheck >/dev/null 2>&1; then
    echo "==> installing shellcheck"
    "${PYTHON}" -m pip install --user --quiet 'shellcheck-py==0.10.0.1'
fi
