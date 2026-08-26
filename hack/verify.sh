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

echo "==> gap-all.sh orchestrates every gap-*.py and runs feature-gates last"
mapfile -t gap_scripts < <(find scripts -maxdepth 1 -name 'gap-*.py' -type f -printf '%f\n' | sort)
mapfile -t orchestrated < <(grep -E 'python3 "\$\{SCRIPT_DIR\}/gap-[a-z0-9-]+\.py"' scripts/gap-all.sh \
    | grep -oE 'gap-[a-z0-9-]+\.py' || true)

if [[ ${#orchestrated[@]} -eq 0 ]]; then
    fail "No python3 gap-*.py invocations found in scripts/gap-all.sh"
else
    last="${orchestrated[-1]}"
    if [[ "${last}" != "gap-feature-gates.py" ]]; then
        fail "Feature gates must run last in gap-all.sh (last invocation is ${last})"
    fi
fi

declare -A orchestrated_set=()
for name in "${orchestrated[@]}"; do
    orchestrated_set["${name}"]=1
done

for name in "${gap_scripts[@]}"; do
    if [[ -z "${orchestrated_set[${name}]+x}" ]]; then
        fail "${name} is not invoked from scripts/gap-all.sh"
    fi
done

if [[ "${FAILED}" -ne 0 ]]; then
    echo "verify FAILED" >&2
    exit 1
fi

echo "verify OK"
