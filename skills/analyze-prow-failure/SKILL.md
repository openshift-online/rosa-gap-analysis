---
name: analyze-prow-failure
description: >
  Analyze latest failed Prow CI job for gap-analysis validation failures.
  Downloads artifacts from GCS, parses JSON reports, generates failure summary.
  Checks top 5 recent jobs automatically. Supports specific job ID analysis.
compatibility:
  required_tools:
    - oc
    - jq
    - gcloud
---

# Analyze Prow Failure

Analyzes failed Prow CI jobs for gap-analysis validation failures.

## When to Use

- Latest Prow job failed and you need to understand what's missing
- Preparing to create PR for new OCP version credentials
- Want failure summary before generating fixes

## What This Analyzes

**Checks latest failed job:**
- Queries Prow deck API for recent failures (top 5 jobs)
- Downloads gap-analysis reports from GCS
- Copies prowjob.json for job metadata (used for PR URL generation)
- Parses validation failures (CHECK #1-5)
- Generates failure summary with file content needed

**Work Directory:**
- Default: `/tmp/gap-analysis-XXXXXX` (temporary)
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
[INFO] Created temporary work directory: /tmp/gap-analysis-AbCd12
[INFO] Finding latest failed job...
[SUCCESS] Found failed job: 2041035894848229376
[SUCCESS] Downloaded artifacts
[SUCCESS] ✅ Analysis complete!
[SUCCESS] Work directory: /tmp/gap-analysis-AbCd12/
/tmp/gap-analysis-AbCd12
```

**Graceful exit (no failures):**
```
[SUCCESS] ✅ No failed jobs in the last 5 executions
[INFO] All recent jobs are successful. No analysis needed.
```

## Options

```bash
# Analyze latest failure (checks top 5)
./ci/analyze-prow-failure.sh

# Keep temp directory for review
./ci/analyze-prow-failure.sh --keep-work-dir

# Use persistent directory
./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis

# Analyze specific job
./ci/analyze-prow-failure.sh --job-id 2041035894848229376 --work-dir ~/prow-analysis
```

## Integration with Other Skills

**Followed by:**
- `fix-prow-failure` - Generates fixes and creates PR

**Use after:**
- `trigger-prow-job` - Manual job trigger
