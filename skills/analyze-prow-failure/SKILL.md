---
name: analyze-prow-failure
description: >
  Analyze most recent Prow CI job for gap-analysis validation failures.
  Downloads artifacts from GCS, parses JSON reports, generates failure summary.
  Checks most recent job automatically. Supports specific job ID analysis.
compatibility:
  required_tools:
    - oc
    - jq
    - gcloud
---

# Analyze Prow Failure

Analyzes most recent Prow CI job for gap-analysis validation failures.

## When to Use

- Most recent Prow job failed and you need to understand what's missing
- Preparing to create PR for new OCP version credentials
- Want failure summary before generating fixes

## What This Analyzes

**Checks most recent job:**
- Queries Prow deck API for most recent job status
- Downloads gap-analysis reports from GCS if job failed
- Copies prowjob.json for job metadata (used for PR URL generation)
- Parses validation failures (CHECK #1-5)
- Generates failure summary with file content needed

**Work Directory:**
- Default: `.tmp/gap-work/analysis-XXXXXX` (temporary, within repo)
- Custom: `--work-dir ~/prow-analysis` (persistent)
- Outputs path on last line for use by fix-prow-failure.sh

## Workflow

### Back-to-back with fix-prow-failure (recommended)

```bash
# Analyze and create PR in one command
WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \
  ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr
```

### Manual review workflow

```bash
# Analyze with persistent directory
./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis

# Review artifacts
cat ~/prow-analysis/failure-summary.md

# Create PR after review
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr
```

## Output

**Successful analysis:**
```
[INFO] Created temporary work directory: .tmp/gap-work/analysis-AbCd12
[INFO] Finding latest failed job...
[SUCCESS] Found failed job: 2041035894848229376
[SUCCESS] Downloaded artifacts
[SUCCESS] ✅ Analysis complete!
[SUCCESS] Work directory: .tmp/gap-work/analysis-AbCd12/
.tmp/gap-work/analysis-AbCd12
```

**Graceful exit (no failures):**
```
[SUCCESS] ✅ Most recent job is successful or pending
[INFO] Most recent job is success. No analysis needed.
```

## Options

```bash
# Analyze most recent job
./ci/analyze-prow-failure.sh

# Keep temp directory for review
./ci/analyze-prow-failure.sh --keep-work-dir

# Use persistent directory
./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis

# Analyze specific job
./ci/analyze-prow-failure.sh --job-id 2041035894848229376 --work-dir ~/prow-analysis
```

## Integration with Other Skills

**Automated alternative:**
- `prow-autofix` - One-step workflow combining analyze + fix + PR (recommended for automation)

**Followed by (manual workflow):**
- `fix-prow-failure` - Generates fixes and creates PR

**Use after:**
- `trigger-prow-job` - Manual job trigger
