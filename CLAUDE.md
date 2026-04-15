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
3. Shared libraries (`scripts/lib/`, `ci/lib/`) - Version resolution, validation, reporting, CI utilities

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
./ci/trigger-prow-job.sh -w

# Analyze failure and create PR (back-to-back workflow)
WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \
  ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr

# Manual review workflow with persistent directory
./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr
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
- Sets `GAP_FULL_REPORT=1` to skip individual MD/HTML (generates JSON only)
- Feature gates runs last, aggregates reports via `generate-combined-report.py`, exits 1 on failures

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

**Manual trigger (ci/trigger-prow-job.sh):**
- Requires auth to OpenShift CI cluster
- Uses Gangway API for triggering jobs (write operations)
- `-w` flag polls for completion via Prow deck API

**Failure analyzer (ci/analyze-prow-failure.sh):**
- Queries Prow deck API for latest FAILED job, downloads artifacts from GCS
- Checks 5 most recent jobs; exits gracefully if all successful
- Parses JSON report → extracts validation failures (CHECK #1-5) → generates fix content
- Work directory: `/tmp/gap-analysis-*` (temp) or `--work-dir` (persistent)
- Outputs failure-summary.md with missing files, permission changes, exact fix content
- Libraries: prow-api.sh, failure-parser.sh, generate-fixes.py, validate-wif-template.sh

**PR creator (ci/fix-prow-failure.sh):**
- Generates files → validates (JSON, YAML, WIF via `validate-wif-template.sh`) → creates PR
- WIF validation: service account ID (max 25 chars), role ID (max 50 chars), format checks; requires `yq`
- Work directory: requires `--work-dir`; auto-cleanup for temp dirs, preserves user-specified paths
- PR template (`ci/templates/pr-body.md`): URLs (Prow job, HTML report), versions, failure summary, file counts, permission changes per-file
- AWS permissions: shows per-file added/removed actions in PR description
- Conditional OCP acks: skips config.yaml if no gates found
- File staging: commits ALL files (gap-analysis + make-generated), PR description lists only gap-analysis files
- Workflow: clone fork → create branch `ocp-X.XX-gap-analysis-update` → generate → make → commit → PR
- Prevents duplicate PRs by checking existing branch

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

**Core analysis:**
- `oc` (OpenShift CLI)
- `python3`
- `PyYAML` (`pip install pyyaml`)
- `curl` (Sippy API)
- `jq` (bash JSON parsing)

**CI/failure analysis:**
- `gcloud` (GCS artifact downloads via `gcloud storage cp`)

**PR creation (fix-prow-failure.sh):**
- `yq` (WIF template validation) - https://github.com/mikefarah/yq

No requirements.txt - dependencies installed manually or in Containerfile.
