#!/usr/bin/env bash
# Repo-specific static checks for `make lint` (Python/bash equivalent of
# certman-operator go-check + yaml-validate).
# Does not invoke pre-commit; pre-commit calls `make lint` locally.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python3}"
FAILED=0

fail() {
    echo "ERROR: $*" >&2
    FAILED=1
}

echo "==> Python syntax (compileall)"
if ! "${PYTHON}" -m compileall -q scripts ci; then
    fail "Python compileall failed"
fi

echo "==> Bash syntax (bash -n)"
while IFS= read -r -d '' file; do
    if ! bash -n "${file}"; then
        fail "Bash syntax error in ${file}"
    fi
done < <(find scripts ci hack -name '*.sh' -type f -print0 | sort -z)

echo "==> Jinja2 template compile"
if ! "${PYTHON}" - <<'PY'
import sys
from pathlib import Path
from jinja2 import TemplateSyntaxError

sys.path.insert(0, str(Path("scripts/lib").resolve()))
from reporters import TEMPLATE_DIR, jinja_env

failed = False
templates = sorted(TEMPLATE_DIR.rglob("*.j2"))
for path in templates:
    name = path.relative_to(TEMPLATE_DIR).as_posix()
    try:
        jinja_env.get_template(name)
    except TemplateSyntaxError as exc:
        print(f"ERROR: Jinja2 syntax error in {path}: {exc}", flush=True)
        failed = True
if failed:
    raise SystemExit(1)
print(f"Compiled {len(templates)} templates")
PY
then
    fail "Jinja2 template compile failed"
fi

echo "==> Gap script HTML templates"
shopt -s nullglob
for script in scripts/gap-*.py; do
    name="$(basename "${script}" .py)"
    name="${name#gap-}"
    template="scripts/templates/${name}.html.j2"
    if [[ ! -f "${template}" ]]; then
        fail "Missing ${template} for ${script}"
    fi
done
if [[ -f scripts/prod/gap-ga-validation.py && ! -f scripts/templates/ga-validation.html.j2 ]]; then
    fail "Missing scripts/templates/ga-validation.html.j2 for scripts/prod/gap-ga-validation.py"
fi

echo "==> CLI --help smoke tests"
help_scripts=(scripts/gap-*.py scripts/generate-combined-report.py)
if [[ -f scripts/prod/gap-ga-validation.py ]]; then
    help_scripts+=(scripts/prod/gap-ga-validation.py)
fi
for script in "${help_scripts[@]}"; do
    if ! "${PYTHON}" "${script}" --help >/dev/null; then
        fail "--help failed for ${script}"
    fi
done

echo "==> gap-all.sh delegates to step-registry commands.sh; every gap-*.py is wired; feature-gates last"
REGISTRY="ci-operator/step-registry/rosa/gap-analysis"

# gap-all.sh must delegate to the step-registry (single source of check logic),
# not call the gap-*.py scripts directly.
if grep -qE 'python3 "\$\{SCRIPT_DIR\}/gap-[a-z0-9-]+\.py"' scripts/gap-all.sh; then
    fail "scripts/gap-all.sh still calls gap-*.py directly; it must delegate to step-registry commands.sh"
fi
if ! grep -q 'run_all_steps' scripts/gap-all.sh; then
    fail "scripts/gap-all.sh is missing run_all_steps (step delegation)"
fi

# Every scripts/gap-*.py must be invoked by a step-registry check commands.sh.
mapfile -t gap_scripts < <(find scripts -maxdepth 1 -name 'gap-*.py' -type f -exec basename {} \; | sort)
if [[ ${#gap_scripts[@]} -eq 0 ]]; then
    fail "No scripts/gap-*.py found"
fi
for name in "${gap_scripts[@]}"; do
    hits=$(grep -rlF "${name}" "${REGISTRY}" 2>/dev/null | grep -c 'commands\.sh' || true)
    if [[ "${hits}" -eq 0 ]]; then
        fail "${name} is not invoked by any step-registry commands.sh"
    fi
done

# Feature gates must run last in gap-all.sh's ordered_steps array.
ga_last=$(awk '
    /local ordered_steps=\(/ {cap=1}
    cap {
        line=$0
        sub(/.*ordered_steps=\(/, "", line)
        sub(/\).*/, "", line)
        buf = buf " " line
        if ($0 ~ /\)/) cap=0
    }
    END {
        n = split(buf, a, /[ \t]+/)
        for (i=n; i>=1; i--) if (a[i] != "") { print a[i]; break }
    }
' scripts/gap-all.sh)
if [[ "${ga_last}" != "feature-gates" ]]; then
    fail "Feature gates must be last in gap-all.sh ordered_steps (last is '${ga_last}')"
fi

# Feature gates must also be last in the checks chain consumed by ci-operator.
chain="${REGISTRY}/checks/rosa-gap-analysis-checks-chain.yaml"
chain_last=$(grep -E '^[[:space:]]*-[[:space:]]*ref:' "${chain}" 2>/dev/null \
    | tail -1 | grep -oE 'rosa-gap-analysis-[a-z0-9-]+' || true)
if [[ "${chain_last}" != "rosa-gap-analysis-feature-gates" ]]; then
    fail "Feature gates must be last in the checks chain (last is '${chain_last}')"
fi

if [[ "${FAILED}" -ne 0 ]]; then
    echo "verify FAILED" >&2
    exit 1
fi

echo "verify OK"
