---
name: fix-prow-failure
description: >
  Fix Prow CI validation failures by generating required files, validating,
  and creating PRs. Generates AWS STS policies, GCP WIF templates, and
  acknowledgment files. Uses template-based PR descriptions with URLs,
  permission changes, and conditional OCP acknowledgments.
compatibility:
  required_tools:
    - python3
    - PyYAML
    - jq
    - yq (WIF template validation)
    - gh
---

# Fix Prow Failure

Generates fixes for Prow CI validation failures and creates comprehensive PRs.

## When to Use

- Prow CI validation failed
- Preparing PR for new OCP version credential policies
- After running `analyze-prow-failure` skill

## What This Generates

1. **AWS STS Policy Files** - IAM policy JSON from OCP CredentialRequests
2. **GCP WIF Template** - Workload identity template (copy-and-update strategy)
3. **Acknowledgment Files** - config.yaml and cloudcredential.yaml for each platform
4. **Validation** - JSON/YAML syntax + WIF template validation (service account/role ID length and format)
5. **PR with Template** - Automated description with URLs, permission changes, file counts

## Workflow

### Back-to-back (recommended)

```bash
# Analyze and fix in one command (temp dir auto-cleaned)
WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \
  ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr
```

### Manual review

```bash
# Analyze with persistent directory
./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis

# Review
cat ~/prow-analysis/failure-summary.md

# Fix and create PR
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr
```

## Generate and Validate

```bash
# Generate and validate only (no PR)
./ci/fix-prow-failure.sh --work-dir /tmp/gap-analysis-AbCd12

# Generate, validate, and create PR
./ci/fix-prow-failure.sh --work-dir /tmp/gap-analysis-AbCd12 --create-pr
```

**What happens:**
1. Reads gap-analysis JSON report
2. Generates AWS STS policies (7 files)
3. Generates GCP WIF template (1 file)
4. Generates acknowledgment files (4-5 files)
5. Validates all files
6. (If --create-pr) Creates PR with template
7. (If temp dir) Cleans up after successful PR

## Output

```
[INFO] Reading gap analysis report: /tmp/gap-analysis-AbCd12/gap-analysis-full_*.json
[INFO] Generating AWS STS policy files...
[SUCCESS] Generated 7 AWS STS policy files

[INFO] Generating GCP WIF template...
[SUCCESS] Generated 1 GCP WIF template

[INFO] Validating generated files...
[SUCCESS] ✅ Validation passed!

[INFO] Creating pull request...
[SUCCESS] ✅ PR created: https://github.com/openshift/managed-cluster-config/pull/1234
[INFO] Cleaning up temporary work directory
[SUCCESS] ✓ Complete!
```

## PR Template Features

**Automatic extraction:**
- Prow Job URL (from job ID)
- HTML Report URL (GCS web viewer)
- Baseline/Target versions
- Validation failure summary

**Permission changes (per-file):**
- Shows file name with specific permissions added/removed
- Example: `0000_30_cluster-api_01_credentials-request.yaml: Added: ec2:AllocateHosts, ec2:ReleaseHosts`

**Conditional OCP acks:**
- Only creates config.yaml if admin gates exist
- Shows note if no gates: "No OCP admin gates found for version X.XX"

**File handling:**
- Commits ALL files: 12 gap-analysis + make-generated files (~17 total after make)
- PR description lists ONLY gap-analysis files (AWS STS: 7, GCP WIF: 1, Acks: 4)
- Make-generated files (ACM policies, hack templates) are committed but not highlighted in PR body

## Options

```bash
# Generate only (no PR)
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis

# Create test PR
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr --test-mode

# Create production PR
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr

# Dry run
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr --dry-run
```

## Configuration

Set via `.github-pr-config` or environment variables:

```bash
TARGET_REPO="openshift/managed-cluster-config"
TEST_REPO="your-user/test-repo"
FORK_REPO="bot-user/managed-cluster-config"
GH_TOKEN="ghp_yourToken"  # Required for PR creation
```

## Integration with Other Skills

**Use after:**
- `analyze-prow-failure` - Provides work directory with failure reports

**Creates:**
- PR in managed-cluster-config with comprehensive description
