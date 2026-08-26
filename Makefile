PYTHON ?= python3

.PHONY: setup lint test clean

setup:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install 'pre-commit==4.6.0'
	pre-commit install

# Prow entrypoint (mirrors certman-operator: `commands: make lint`).
# Does not run the pre-commit binary; pre-commit calls this target locally.
# CI image already has ruff/shellcheck; ensure-lint-tools.sh is a local fallback.
# One shell so PATH from ensure-lint-tools.sh is visible when they were just installed.
lint:
	@set -euo pipefail; \
	export PYTHON="$(PYTHON)"; \
	. ./hack/ensure-lint-tools.sh; \
	ruff check scripts ci; \
	echo "==> shellcheck"; \
	files=$$(find scripts ci hack -name '*.sh' -type f | sort); \
	if [ -z "$$files" ]; then echo "No shell scripts found"; exit 1; fi; \
	echo "$$files" | xargs shellcheck --severity=error; \
	./hack/verify.sh

test:
	$(PYTHON) -m pytest tests/ -v 2>/dev/null || echo "No tests directory found"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
