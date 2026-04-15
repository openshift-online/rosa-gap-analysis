# Testing Guide - Prow Failure Analysis & Fix

Quick testing guide for the analyze/fix workflow.

## Prerequisites

- `oc` - Authenticated to OpenShift CI cluster
- `jq`, `gcloud`, `gh` - Standard tooling
- `GH_TOKEN` - GitHub Personal Access Token
- Fork of `managed-cluster-config` (for PR testing)

## Work Directory Setup

**Recommended (temp directory):**
```bash
WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \
  ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr
```

**For testing (persistent directory):**
```bash
./ci/analyze-prow-failure.sh --work-dir ~/test-work
./ci/fix-prow-failure.sh --work-dir ~/test-work
```

## Core Test Cases

### Test 1: Analyze Latest Failure

```bash
# Check top 5 recent jobs for failures
./ci/analyze-prow-failure.sh --work-dir ~/test-work

# Review results
cat ~/test-work/failure-summary.md
ls ~/test-work/gap-analysis-full_*.json
```

**Expected:** Downloads artifacts, generates failure summary.

### Test 2: Generate and Validate Fixes

```bash
# Generate fix files
./ci/fix-prow-failure.sh --work-dir ~/test-work

# Review generated files
tree ~/test-work/managed-cluster-config/
```

**Expected:** Creates AWS STS policies, GCP WIF templates, ack files. Validates all.

### Test 3: Create Test PR

```bash
# Set up test configuration
export GH_TOKEN="ghp_your_token"

# Create PR to test repository
./ci/fix-prow-failure.sh --work-dir ~/test-work --create-pr --test-mode
```

**Expected:** PR created with template-based description, URLs, permission changes.

### Test 4: Back-to-Back Workflow

```bash
# Full workflow: analyze and create PR in one command
WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \
  ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr --test-mode
```

**Expected:** Temp directory auto-cleaned after successful PR.

### Test 5: Specific Job Analysis

```bash
# Analyze specific failed job by ID
./ci/analyze-prow-failure.sh --job-id 2041035894848229376 --work-dir ~/test-work
```

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
- All top 5 jobs are successful → expected graceful exit
- Use `--job-id` to analyze older failed job

**GH_TOKEN not set:**
```bash
export GH_TOKEN="ghp_yourTokenHere"
```

**Fork not configured:**
- Update `FORK_REPO` in configuration or use `--fork-repo` flag

## Cleanup

```bash
# Remove test artifacts
rm -rf ~/test-work

# Check for orphaned temp directories
ls /tmp/gap-analysis-* 2>/dev/null
```
