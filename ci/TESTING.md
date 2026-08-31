# Testing Guide - Prow Failure Analysis & Fix

Quick testing guide for the analyze/fix workflow.

## Prerequisites

- `oc` - Authenticated to OpenShift CI cluster
- `jq`, `gcloud`, `gh` - Standard tooling
- Fork of `managed-cluster-config` (rosa-gap-analysis-bot/managed-cluster-config)

**Required setup (GH_TOKEN must be set):**
```bash
# Set GitHub Personal Access Token for rosa-gap-analysis-bot (REQUIRED)
export GH_TOKEN="ghp_yourToken"
```

**Important:** The script validates that `GH_TOKEN` (or `GITHUB_TOKEN`) is set and will fail early if missing.

**That's it!** All other configuration is standardized in `ci/pr-defaults.sh` - no additional setup required.

**Optional overrides** via environment variables or command-line flags (see `ci/pr-defaults.sh` for available variables).

## Workflows

Choose the appropriate workflow based on your testing needs:

### Automated Workflow (Recommended for Testing)

**One-step command:**
```bash
export GH_TOKEN="ghp_yourToken"  # REQUIRED
./ci/prow-autofix.sh
```

This automatically:
1. Analyzes latest failed job
2. Generates fix files
3. Creates PR
4. Cleans up temp directory

**When to use:** Automated testing, CI/CD integration, trusted workflow

**Options:**
```bash
# Test mode (PR to test repo)
export TEST_REPO="your-user/test-managed-cluster-config"
./ci/prow-autofix.sh --test-mode

# Dry run (preview without PR, preserves work dir)
./ci/prow-autofix.sh --dry-run

# Specific job
./ci/prow-autofix.sh --job-id 2041035894848229376
```

### Manual Workflow (For Review/Debugging)

**When to use:** Need to review failure summary before PR, debugging, investigation

**Two-step with temp directory:**
```bash
export GH_TOKEN="ghp_yourToken"  # REQUIRED for step 2
WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \
  ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr
```

**Two-step with persistent directory:**
```bash
export GH_TOKEN="ghp_yourToken"  # REQUIRED for step 2
./ci/analyze-prow-failure.sh --work-dir ~/test-work
# Review ~/test-work/failure-summary.md
./ci/fix-prow-failure.sh --work-dir ~/test-work --create-pr
```

## Core Test Cases

### Test 1: Trigger Prow Job (Manual)

```bash
# List matching periodics, then trigger one and monitor
./ci/trigger-prow-job.sh
./ci/trigger-prow-job.sh -j periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-4-22 --wait
```

**Expected:** Triggers job, polls status every 30s, displays final result.

**Validates:** Job triggering workflow, Gangway API integration.

### Test 2: Automated Fix Workflow (One-Step)

```bash
export GH_TOKEN="ghp_your_token"
export TEST_REPO="your-user/test-managed-cluster-config"

# One-step automated workflow (all matching periodics, or pass --job-name)
./ci/prow-autofix.sh --test-mode --skip-if-pr-exists
```

**Expected:** Discovers matching periodics whose latest run failed. For each, generates fixes and either creates a PR or skips if an open MCC PR already exists for that OCP minor (`--skip-if-pr-exists`). A successful run may create zero, one, or several PRs. Auto-cleans temp directory after PR creation.

**Validates:** Complete automation pipeline, duplicate-PR skip, standardized PR configuration.

### Test 3: Automated Dry Run

```bash
# Preview without creating PR
./ci/prow-autofix.sh --dry-run
```

**Expected:**
- Analyzes latest failure
- Generates and validates files
- Skips PR creation
- Preserves work directory (not cleaned up, for inspection)
- Outputs work directory path for manual review

**Validates:** Generation and validation logic without PR side effects.

### Test 4: Manual Workflow - Analyze Only

```bash
# Check most recent job
./ci/analyze-prow-failure.sh --work-dir ~/test-work

# Review results
cat ~/test-work/failure-summary.md
ls ~/test-work/gap-analysis-full_*.json
```

**Expected:** Downloads artifacts from latest failed job, generates failure summary.

**Validates:** Prow deck API integration, artifact download, failure parsing.

### Test 5: Manual Workflow - Generate and Validate

```bash
# Generate fix files (requires prior analyze step)
./ci/fix-prow-failure.sh --work-dir ~/test-work

# Review generated files
tree ~/test-work/managed-cluster-config/
```

**Expected:** Creates AWS STS policies, GCP WIF templates, ack files. Validates JSON/YAML syntax and WIF template constraints.

**Validates:** File generation logic, WIF validation (service account ID ≤25 chars, role ID ≤50 chars).

### Test 6: Manual Workflow - Create PR

```bash
export GH_TOKEN="ghp_your_token"
export TEST_REPO="your-user/test-managed-cluster-config"

# Create PR to test repository
./ci/fix-prow-failure.sh --work-dir ~/test-work --create-pr --test-mode
```

**Expected:** PR created with template-based description, Prow job URL, HTML report URL, per-file permission changes.

**Validates:** PR template, permission change extraction, file counting, duplicate PR detection.

### Test 7: Specific Job Analysis

```bash
# Analyze specific failed job by ID
./ci/analyze-prow-failure.sh --job-id 2041035894848229376 --work-dir ~/test-work
```

**Expected:** Downloads artifacts for specified job, bypasses top-5 check.

**Validates:** Direct job ID analysis (useful for older failures).

## Validation Checks

**Verify PR template includes:**
- Prow job URL
- HTML report URL
- AWS permission changes (added/removed)
- Conditional OCP ack note (if no gates)
- Correct file counts (12 gap-analysis files)

**Verify work directory cleanup:**
```bash
# Check /tmp directories are cleaned after PR
ls /tmp/gap-analysis-* 2>/dev/null || echo "✓ Cleaned up"

# Check persistent directories preserved
ls ~/test-work/ && echo "✓ Preserved for review"
```

## Common Issues

**No failures found:**
- Most recent job is successful → expected graceful exit
- Use `--job-id` to analyze specific older failed job

**GH_TOKEN not set:**
```
ERROR: GitHub Personal Access Token (PAT) is required!
```
Solution:
```bash
export GH_TOKEN="ghp_yourTokenHere"
```
The script validates this early and will fail immediately if not set.

**Override standard configuration (if needed):**
```bash
# All defaults work out of the box. Override only if needed.
# See ci/pr-defaults.sh for available variables.

# Via environment variables
export FORK_REPO="different-user/managed-cluster-config"

# Via command-line flags
./ci/fix-prow-failure.sh --fork-repo "..."
```

**Test repository for --test-mode:**
```bash
# Via environment variable (preferred)
export TEST_REPO="your-user/test-managed-cluster-config"

# OR via flag
./ci/fix-prow-failure.sh --test-mode --test-repo "your-user/test-repo"
```

## Cleanup

```bash
# Remove test artifacts
rm -rf ~/test-work

# Check for orphaned temp directories
ls /tmp/gap-analysis-* 2>/dev/null
```

## See Also

- [CI README](README.md) - Complete documentation for all CI workflows
- [Quick Start](README.md#quick-start) - Three main workflow options
- [Workflow Comparison](README.md#workflow-comparison) - When to use automated vs manual
- [Configuration](README.md#configuration) - Required GH_TOKEN and optional overrides
- [PR Defaults](pr-defaults.sh) - Standard configuration values
