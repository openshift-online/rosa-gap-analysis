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
- **Reports**: All scripts generate HTML/JSON simultaneously using Jinja2 templates
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

# Automated Prow failure fix (recommended)
export GH_TOKEN="..." && ./ci/prow-autofix.sh

# Manual Prow job trigger
./ci/trigger-prow-job.sh -w

# Manual review workflow
./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr
```

## Validation Checks

| Check # | Script | Validates | Exit on FAIL |
|---------|--------|-----------|--------------|
| **1** | gap-aws-sts.py | AWS STS policy files in `resources/sts/{version}/` match OCP release (per-file comparison) | Yes |
| **2** | gap-aws-sts.py | AWS acknowledgment files in `deploy/osd-cluster-acks/sts/{version}/` | Yes |
| **3** | gap-gcp-wif.py | GCP WIF templates in `resources/wif/{version}/` match OCP release (per-file comparison) | Yes |
| **4** | gap-gcp-wif.py | GCP acknowledgment files in `deploy/osd-cluster-acks/wif/{version}/` | Yes |
| **5** | gap-ocp-gate-ack.py | OCP admin gate acknowledgments in `deploy/osd-cluster-acks/ocp/{version}/` (conditional: if gates exist, both config.yaml + admin-ack.yaml required; if no gates, both files must be absent) | Yes |
| **6** | gap-feature-gates.py | Feature gate changes (informational) | No |

**Expected baseline**: For target X.Y, baseline is X.(Y-1). Example: 4.22 expects 4.21 baseline.

## Critical Implementation Details

**gap-all.sh orchestrator:**
- Sets `GAP_FULL_REPORT=1` to skip individual HTML (generates JSON only)
- Feature gates runs last, aggregates reports via `generate-combined-report.py`, exits 1 on failures

**Version resolution (openshift_releases.py/sh):**
- **API endpoint**: Uses `/api/v1/releasestreams/accepted` (single call for both 4-stable and 4-dev-preview)
- **Baseline**: Latest GA version line (e.g., 4.21.x) from 4-stable accepted stream, filtered by GA version from Sippy API
- **Target**: GA+1 version (e.g., 4.22.x) - first checks 4-stable for RC (4.22.0-rc.*), falls back to 4-dev-preview for EC (4.22.0-ec.*)
- **CLI/ENV resolution**: Minor versions (e.g., `--baseline 4.21 --target 4.22`) are resolved the same way as auto-detect (4.21 → 4.21.11, 4.22 → 4.22.0-rc.0); full versions (e.g., `4.21.7`, `4.22.0-rc.0`) are used as-is
- Auto-detect: queries Sippy API for GA version (e.g., 4.21), then filters accepted streams
- Keywords: `NIGHTLY` → latest dev nightly, `CANDIDATE` → latest dev candidate (RC from stable or EC from dev-preview)
- Minor version normalization: `4.21.7` → `4.21` for feature gates API
- **Quick version queries**: See README.md Quick Reference for curl commands to query accepted streams

**Validation (ack_validation.py):**
- Fetches files from managed-cluster-config GitHub repo via HTTPS
- Uses git sparse-checkout for efficient directory fetching
- Validates policy files match OCP release credential requests using **per-file comparison**
- Per-file validation: Aggregates all permission changes across individual CredentialRequest files, not just globally-new permissions (a permission can be new to one CR but already exist in another)
- Checks acknowledgment files (config.yaml, cloudcredential.yaml) for required structure
- Detects related PRs using GitHub REST API (unauthenticated, 60 req/hour limit) with gh CLI fallback

**Report generation (reporters.py):**
- Templates in `scripts/templates/*.html.j2`
- Timestamped filenames: `gap-analysis-{type}_{baseline}_to_{target}_{timestamp}.{ext}`
- Combined report aggregates all individual JSON reports

**Python import pattern (all scripts):**
```python
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error
from openshift_releases import resolve_baseline_version, resolve_target_version
from reporters import generate_html_report, generate_json_report
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

**Automated fix (ci/prow-autofix.sh):**
- One-step: check job status → if failed: analyze → generate fixes → create PR
- Auto-creates temp directory, auto-cleanup after PR creation
- Requires only `GH_TOKEN` environment variable
- Options: `--test-mode`, `--dry-run`, `--job-id`, `--verbose`
- Recommended for CI/CD and automation workflows

**Configuration (ci/pr-defaults.sh):**
- Standardized defaults: `TARGET_REPO`, `FORK_REPO`, `LABELS`, `REVIEWERS`, `GITHUB_USERNAME`, `GIT_USER_NAME`, `GIT_USER_EMAIL`
- Optional overrides via environment variables or command-line flags
- Required: `GH_TOKEN` for GitHub API access

**Manual trigger (ci/trigger-prow-job.sh):**
- Requires auth to OpenShift CI cluster
- Uses Gangway API for triggering jobs (write operations)
- `-w` flag polls for completion via Prow deck API

**Manual analyzer (ci/analyze-prow-failure.sh):**
- Checks most recent Prow job; downloads artifacts from GCS if failed
- Exits gracefully if most recent job is successful
- Parses JSON report → extracts validation failures (CHECK #1-5) → generates fix content
- Work directory: `.tmp/gap-work/analysis-*` (temp) or `--work-dir` (persistent)
- Outputs failure-summary.md with missing files, permission changes, exact fix content
- Use `--job-id` to analyze specific older failed jobs

**File generation (ci/lib/generate-fixes.py):**
- **Copy-first strategy**: Copies ALL files from previous version (baseline) to ensure completeness
- **Preserve structure**: Filenames, JSON key casing, and file structure maintained from baseline
- **Update only diffs**: Extracts CredentialRequests from both baseline and target, applies only permission changes
- **No new files**: Updates existing files based on CR matches; infrastructure files (sts_installer_*, sts_instance_*, sts_ocm_*, sts_support_*, operator_iam_role_policy.json, osd_scp_policy.json) copied unchanged
- **Key casing preservation**: Matches IAM policy format from baseline (Action/Effect/Resource capitalized)
- **Fuzzy matching**: Maps target CredentialRequests to baseline filenames using namespace/name matching
- **AWS STS**: Copies from `resources/sts/{baseline}/` → `resources/sts/{target}/`, updates matched CRs only
- **GCP WIF**: Copies from `resources/wif/{baseline}/` → `resources/wif/{target}/`, updates version strings (v4.21 → v4.22)

**Manual PR creator (ci/fix-prow-failure.sh):**
- Generates files → validates (JSON, YAML, WIF via `validate-wif-template.sh`) → **runs `make`** → creates PR
- **Make step (REQUIRED)**: Runs `make` in managed-cluster-config to generate ACM policies and hack templates; PR created ONLY if make succeeds
- **Make verification**: After commit, re-runs `make` to verify idempotency (no changes on re-run); prevents CI check failures
- WIF validation: service account ID (max 25 chars), role ID (max 50 chars), format checks; requires `yq`
- Work directory: requires `--work-dir`; auto-cleanup for temp dirs, preserves user-specified paths
- PR template (`ci/templates/pr-body.md`): URLs (Prow job, HTML report), versions, failure summary, file counts, permission changes per-file
- AWS permissions: shows per-file added/removed actions in PR description
- Conditional OCP acks: skips config.yaml if no gates found
- File staging: commits ALL files (gap-analysis + make-generated), PR description lists only gap-analysis files
- Workflow: clone fork → create branch → copy gap-analysis files → **`make`** → stage all → verify clean → commit → **verify `make` idempotent** → push → PR
- PR replacement: closes existing PR for same branch and creates new one with updated changes

## Development

**Adding new analysis script:**
1. Create `scripts/gap-new-analysis.py` with standard import pattern
2. Create template: `scripts/templates/new-analysis.html.j2`
3. Add to `scripts/gap-all.sh` orchestrator (before feature gates)
4. Update `ci/Containerfile` if new dependencies needed
5. Test with explicit versions before using auto-detect

**Modifying templates:**
- Edit Jinja2 HTML files in `scripts/templates/`
- Common variables: `type`, `baseline`, `target`, `timestamp`, `comparison`, `validation`
- Test by running corresponding script

**Shared libraries:**
- `common.py` - Logging, color codes, command checks, project root detection
- `openshift_releases.py` - Version resolution, Sippy queries, minor version extraction
- `reporters.py` - Multi-format report generation
- `ack_validation.py` - managed-cluster-config validation logic
- `logging.sh` - Bash logging functions
- `openshift-releases.sh` - Bash version resolution
- `ci/lib/failure-parser.sh` - CI-specific Prow failure parsing utilities
- `ci/lib/prow-api.sh` - CI-specific Prow API interaction utilities
- `ci/lib/validate-wif-template.sh` - WIF template validation (service account/role ID constraints)

## Runtime Dependencies

**Core analysis:**
- `oc` (OpenShift CLI)
- `python3`
- `PyYAML` (`pip install pyyaml`)
- `curl` (Sippy API)
- `jq` (bash JSON parsing)
- `gh` (GitHub CLI - optional fallback for PR link detection if GH_TOKEN set)

**CI/failure analysis:**
- `gcloud` (GCS artifact downloads via `gcloud storage cp`)

**PR creation (fix-prow-failure.sh):**
- `yq` (WIF template validation) - https://github.com/mikefarah/yq

Python packages (`PyYAML`, `Jinja2`) listed in `requirements.txt`; install with `pip install -r requirements.txt`. Container dependencies managed via `ci/Containerfile`.
