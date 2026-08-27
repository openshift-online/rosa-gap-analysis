---
name: prow-autofix
description: >
  One-step automated Prow failure fix workflow. Analyzes latest failed CI job,
  generates required files (AWS STS policies, GCP WIF templates, acknowledgments),
  validates, and creates PR to managed-cluster-config. Automatic temporary
  directory cleanup. Recommended for CI/CD pipelines and automated remediation.
compatibility:
  required_tools:
    - oc
    - jq
    - gcloud
    - python3
    - PyYAML
    - yq (WIF template validation)
    - gh
  required_env:
    - GH_TOKEN (or GITHUB_TOKEN)

---

# Prow Autofix - Automated One-Step Workflow

Complete automation from Prow failure analysis to PR creation in a single command.

## When to Use

- **Automated environments** - CI/CD pipelines, scheduled automation
- **Quick fixes** - Don't need to review failure details before PR
- **Trusted workflow** - Standard fix-and-submit process
- **Latest failure** - Automatically find and fix most recent failed job

## What This Does

The `ci/prow-autofix.sh` script provides complete end-to-end automation:

1. **Check status** - Query Prow API to verify most recent job failed (exit gracefully if successful)
2. **Analyze** - Download failed job artifacts from GCS (via `analyze-prow-failure.sh`)
3. **Parse** - Extract validation failures (CHECK #1-5) from gap-analysis reports
4. **Generate** - Create AWS STS policies, GCP WIF templates, acknowledgment files
5. **Validate** - JSON/YAML syntax, WIF template validation (service account/role ID constraints)
6. **Run `make`** - Execute `make` in managed-cluster-config to generate ACM policies and hack templates (PR created only if make succeeds)
7. **Verify idempotency** - Re-run `make` after commit to ensure deterministic behavior (prevents CI check failures)
8. **Create PR** - Template-based description with job URLs, HTML report links, permission changes (closes existing PR if present)
9. **Cleanup** - Automatic temporary directory cleanup after success

## Workflow

This skill combines `analyze-prow-failure` + `fix-prow-failure` into one command.

### Quick Start

```bash
# One-step automated workflow (most common)
/prow-autofix
```

Claude will execute:
```bash
export GH_TOKEN="<your-token>"
./ci/prow-autofix.sh
```

### With Options

```bash
# Test mode (PR to test repository)
/prow-autofix --test-mode

# Dry run (preview without creating PR)
/prow-autofix --dry-run

# Specific job ID
/prow-autofix --job-id 2041035894848229376

# Verbose output
/prow-autofix --verbose
```

## Example Interaction

**User:** "Run prow-autofix to create PR for the latest failure"

**Claude:**
```bash
# Execute automated workflow
./ci/prow-autofix.sh
```

**What happens:**
1. Script checks most recent job status via Prow API
2. If successful, exits gracefully (nothing to fix)
3. If failed, downloads gap-analysis reports from GCS
4. Parses validation failures (CHECK #1-5)
5. Generates AWS STS policies, GCP WIF templates, acknowledgment files
6. Validates all generated files
7. Creates PR to managed-cluster-config
8. Cleans up temporary directory

**Output:**
```
[INFO] Prow Automated Fix Workflow
======================================================================

[INFO] STEP 1/3: Checking job status...
[INFO] Checking most recent job for: periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-4-22...
[INFO] Most recent job status: failure (ID: 2041035894848229376)
[INFO] Most recent job failed. Proceeding with analysis...

[INFO] STEP 2/3: Analyzing failed Prow job...
[SUCCESS] ✓ Analysis complete. Work directory: .tmp/gap-work/analysis-XxXxXx

[INFO] STEP 3/3: Generating fix files and creating pull request...
[SUCCESS] ✓ Pull request created successfully

======================================================================
[SUCCESS] ✓ Automated workflow complete!
PR URL: https://github.com/openshift/managed-cluster-config/pull/12345
======================================================================
```

## Output

**Successful workflow:**
```
[INFO] Prow Automated Fix Workflow
======================================================================

[INFO] STEP 1/3: Checking job status...
[INFO] Most recent job status: failure (ID: 2041035894848229376)
[INFO] Most recent job failed. Proceeding with analysis...

[INFO] STEP 2/3: Analyzing failed Prow job...
[SUCCESS] ✓ Analysis complete. Work directory: .tmp/gap-work/analysis-XxXxXx

[INFO] STEP 3/3: Generating fix files and creating pull request...
[SUCCESS] ✓ Pull request created successfully

======================================================================
[SUCCESS] ✓ Automated workflow complete!
[SUCCESS] ✓ Pull request created successfully
[SUCCESS] PR URL: https://github.com/openshift/managed-cluster-config/pull/XXXX
======================================================================
```

**Graceful exit (no failures):**
```
[INFO] STEP 1/3: Checking job status...
[INFO] Checking most recent job for: periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-4-22...
[INFO] Most recent job status: success (ID: 2046254941009350656)

======================================================================
[SUCCESS] ✓ Most recent job is success - nothing to fix!
======================================================================

[INFO] To analyze a specific older failed job, use: --job-id <JOB_ID>
```

**Dry run mode:**
```
[SUCCESS] ✓ Dry run complete (no PR created)
[INFO] Review generated files in: .tmp/gap-work/analysis-XxXxXx
```

## Options

All options from the underlying script are supported:

```bash
./ci/prow-autofix.sh [OPTIONS]

OPTIONS:
  -j, --job-name NAME    Periodic to analyze (omit to process all matching …-periodics-nightly-*)
  -i, --job-id ID        Analyze specific job by ID
  -t, --test-mode        Create PR to TEST_REPO instead of production
  -d, --dry-run          Preview changes without creating PR
  --generate-only        Generate MCC files only; do not create a GitHub PR
  --skip-if-pr-exists    Skip if an open MCC PR already exists for that OCP minor
  -v, --verbose          Enable verbose output
  -h, --help             Display help
```

## Prerequisites

**Required before using this skill:**

1. **GH_TOKEN set** (required unless `--generate-only` or `--dry-run`):
   ```bash
   export GH_TOKEN="ghp_yourToken"  # Must belong to rosa-gap-analysis-bot
   ```

2. **Standard configuration** (in `ci/pr-defaults.sh`):
   - `TARGET_REPO`, `FORK_REPO`, `REVIEWERS`, `LABELS` already configured
   - No additional setup needed
   - Optional overrides via environment variables or flags (see `ci/pr-defaults.sh` for variables)

3. **Tools installed:**
   - `oc`, `jq`, `gcloud` (analysis)
   - `python3`, `PyYAML`, `yq` (generation/validation)
   - `gh` (PR creation)

## When NOT to Use

Use manual workflow (`analyze-prow-failure` + `fix-prow-failure`) instead when:

- **Need to review** failure details before creating PR
- **Debugging** specific validation failures
- **Investigation** of unusual failures
- **Custom changes** needed beyond standard fix generation
- **Preserve artifacts** for later inspection

Manual workflow allows review between analysis and PR creation.

## Integration with Other Skills

**Alternative to (manual workflow):**
- `analyze-prow-failure` - Analyze failures
- `fix-prow-failure` - Generate fixes and create PR

This skill combines both steps into one automated command.

**Use after:**
- Manual job trigger via Prow UI or CLI
- Scheduled job completion notification

**Workflow example:**
```bash
# After noticing a Prow job failure, run automated fix
./ci/prow-autofix.sh

# Or with specific job ID
./ci/prow-autofix.sh --job-id 2041035894848229376
```

## Configuration

**Standard defaults** (no setup required - see `ci/pr-defaults.sh`):
- `TARGET_REPO="openshift/managed-cluster-config"`
- `FORK_REPO="rosa-gap-analysis-bot/managed-cluster-config"`
- `REVIEWERS="ravitri"`
- `LABELS="area/credentials"`
- `GITHUB_USERNAME="rosa-gap-analysis-bot"`

**Override if needed** (see `ci/pr-defaults.sh` for full list):

```bash
# Via environment variables
export FORK_REPO="different-user/managed-cluster-config"
./ci/prow-autofix.sh

# Or via command-line flags
./ci/prow-autofix.sh --fork-repo "different-user/managed-cluster-config"
```

## Comparison: Automated vs Manual

| Aspect | Automated (this skill) | Manual (two-step) |
|--------|------------------------|-------------------|
| **Commands** | 1 (`prow-autofix.sh`) | 2 (analyze + fix) |
| **Review** | No manual review | Review between steps |
| **Work dir** | Auto temp + cleanup | User-specified, preserved |
| **Speed** | Fastest | Slower (manual steps) |
| **Use case** | Automation, CI/CD | Investigation, debugging |
| **Trust** | High (automated) | Verification (manual) |

## Error Handling

**Common scenarios:**

1. **No failures found:**
   - Checks most recent job status via Prow API
   - Exits gracefully if successful or pending (no analysis performed)
   - Faster than previous implementation (no artifact download needed)
   - Use --job-id to analyze specific older failed jobs (skips status check)

2. **GH_TOKEN not set:**
   - Fails early with a clear error unless `--generate-only` or `--dry-run`
   - Prompts user to set token when `--create-pr` would run

3. **PR already exists:**
   - With `--skip-if-pr-exists`: leave the open PR alone and print its URL
   - Without that flag: update the existing PR for the same `ocp-{minor}-gap-analysis-update` branch

4. **Validation failure:**
   - Shows which file failed validation
   - Preserves work directory for debugging
   - Does not create PR with invalid files

## Notes

- **Temporary directory:** Automatically created and cleaned up after success
- **Failure preservation:** Work directory preserved on error for debugging
- **No duplicate PRs:** `--skip-if-pr-exists` skips when an open MCC PR for that OCP minor already exists
- **Graceful degradation:** Handles missing artifacts, successful jobs gracefully
