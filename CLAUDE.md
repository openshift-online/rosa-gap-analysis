# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Gap analysis framework for managed OpenShift (ROSA/OSD) that validates cloud credential policies and feature gates between OpenShift versions. Prevents upgrade failures by detecting IAM permission changes and missing acknowledgment files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config).

## Working Principles

### Plan Before Implementing

Claude follows an impact-based approach in this repository:

**High-Impact Changes** (affecting multiple files/areas):
- New/removed gap scripts
- Validation logic changes
- Output format changes
- CLI flag modifications
- Shared library changes

**Process:**
1. Show high-level implementation plan
2. List affected files
3. Suggest relevant subagents
4. Wait for approval
5. Execute after "proceed"/"yes"

**Low-Impact Changes** (internal only):
- Bug fixes (same behavior)
- Refactoring (same interface)
- Comments/typos
- Internal optimizations

**Process:**
1. Make change directly
2. Brief explanation
3. No plan/approval needed

**See:** `.claude/rules/when-to-plan.md` for detailed classification criteria.

## Architecture

**3-Layer Design:**
1. Individual analyzers (`scripts/gap-*.py`) - AWS STS, GCP WIF, Feature Gates, OCP Admin Gates
2. Orchestrator (`scripts/gap-all.sh`) - Runs all analyzers, generates combined reports
3. Shared libraries (`scripts/lib/`) - Version resolution, validation, reporting

**Data Sources:**
- `oc adm release extract --credentials-requests` → extracts CredentialsRequest manifests from OCP releases
- Sippy API → feature gate data and version resolution
- managed-cluster-config GitHub repo → validates policy files and acknowledgments

**Key Patterns:**
- **Exit codes**: Exit 0 on successful execution even when differences found; exit 1 only on execution errors
- **Version resolution**: CLI flags > env vars > auto-detect (Sippy API)
- **Reports**: All scripts generate MD/HTML/JSON simultaneously using Jinja2 templates
- **Validation**: 6 globally numbered checks; checks 1-5 can FAIL, check 6 (feature gates) is informational only

## Essential Commands

```bash
# Run all analyses (auto-detects latest stable → candidate)
./scripts/gap-all.sh

# Explicit versions
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# Test against nightly
TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh

# Individual analysis
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22

# Container testing
podman build -f ci/Containerfile -t gap-analysis:dev .
podman run --rm gap-analysis:dev gap-all.sh --baseline 4.21 --target 4.22

# Manual Prow job trigger
./ci/run-prow-job.sh -w
```

## Validation Checks

| Check # | Script | Validates | Exit on FAIL |
|---------|--------|-----------|--------------|
| **1** | gap-aws-sts.py | AWS STS policy files in `resources/sts/{version}/` match OCP release | Yes |
| **2** | gap-aws-sts.py | AWS acknowledgment files in `deploy/osd-cluster-acks/sts/{version}/` | Yes |
| **3** | gap-gcp-wif.py | GCP WIF templates in `resources/wif/{version}/` match OCP release | Yes |
| **4** | gap-gcp-wif.py | GCP acknowledgment files in `deploy/osd-cluster-acks/wif/{version}/` | Yes |
| **5** | gap-ocp-gate-ack.py | OCP admin gate acknowledgments in `deploy/osd-cluster-acks/ocp/{version}/` | Yes |
| **6** | gap-feature-gates.py | Feature gate changes (informational) | No |

**Expected baseline**: For target X.Y, baseline is X.(Y-1). Example: 4.22 expects 4.21 baseline.

## Critical Implementation Details

**gap-all.sh orchestrator:**
- Sets `GAP_FULL_REPORT=1` env var to skip individual MD/HTML reports (only JSON generated)
- Feature gates analysis ALWAYS runs last (even if new checks added in future)
- Calls `generate-combined-report.py` to aggregate individual JSONs into combined report
- Exit 1 if any check fails OR execution error occurs

**Version resolution (openshift_releases.py/sh):**
- Auto-detect: queries Sippy API for latest stable (baseline) and candidate (target)
- Keywords: `NIGHTLY` → latest dev nightly, `CANDIDATE` → latest dev candidate
- Minor version normalization: `4.21.7` → `4.21` for feature gates API

**Validation (ack_validation.py):**
- Fetches files from managed-cluster-config GitHub repo via HTTPS
- Uses git sparse-checkout for efficient directory fetching
- Validates policy files match OCP release credential requests
- Checks acknowledgment files (config.yaml, cloudcredential.yaml) for required structure

**Report generation (reporters.py):**
- Templates in `scripts/templates/*.{md,html}.j2`
- Timestamped filenames: `gap-analysis-{type}_{baseline}_to_{target}_{timestamp}.{ext}`
- Combined report aggregates all individual JSON reports

**Credential request parsing (parse-credentials-request.py):**
- AWS: extracts `spec.providerSpec.statementEntries` (IAM actions)
- GCP: extracts `spec.providerSpec.permissions` (GCP permissions)

**Python import pattern (all scripts):**
```python
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error
from openshift_releases import resolve_baseline_version, resolve_target_version
from reporters import generate_markdown_report, generate_html_report, generate_json_report
```

**Logging convention:**
- `log_info()`, `log_success()`, `log_warning()`, `log_error()` → stderr
- Color-coded: Blue [INFO], Green [SUCCESS], Yellow [WARNING], Red [ERROR]
- Stdout reserved for report generation

## CI/CD Integration

**Container (ci/Containerfile):**
- Base: UBI9
- Includes: `oc` CLI, Python 3, PyYAML, curl, bash
- Scripts pre-installed at `/gap-analysis/scripts/` and in PATH
- Writable temp dirs (`/tmp/.cache`, `/tmp/gap-analysis-data`) for random UID support
- Working directory: `/gap-analysis`

**Prow jobs:**
- Use `build_root.project_image.dockerfile_path: ci/Containerfile`
- Scripts execute directly (no repo clone needed)
- Reports saved to `${ARTIFACT_DIR}` if specified via `REPORT_DIR` env var

**Manual trigger (ci/run-prow-job.sh):**
- Requires auth to OpenShift CI cluster
- `-w` flag polls for completion
- Validates job existence via Gangway API

## Development

**Adding new analysis script:**
1. Create `scripts/gap-new-analysis.py` with standard import pattern
2. Create templates: `scripts/templates/new-analysis.{md,html}.j2`
3. Add to `scripts/gap-all.sh` orchestrator (before feature gates)
4. Update `ci/Containerfile` if new dependencies needed
5. Test with explicit versions before using auto-detect

**Modifying templates:**
- Edit Jinja2 files in `scripts/templates/`
- Common variables: `type`, `baseline`, `target`, `timestamp`, `comparison`, `validation`
- Test by running corresponding script

**Shared libraries:**
- `common.py` - Logging, color codes, command checks, project root detection
- `openshift_releases.py` - Version resolution, Sippy queries, minor version extraction
- `reporters.py` - Multi-format report generation
- `ack_validation.py` - managed-cluster-config validation logic
- `common.sh`, `openshift-releases.sh` - Bash equivalents

## Runtime Dependencies

- `oc` (OpenShift CLI)
- `python3`
- `PyYAML` (`pip install pyyaml`)
- `curl` (Sippy API)
- `jq` (bash JSON parsing)

No requirements.txt - dependencies installed manually or in Containerfile.
