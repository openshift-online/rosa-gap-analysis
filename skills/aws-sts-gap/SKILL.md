---
name: aws-sts-gap
description: >
  Analyze AWS STS (Security Token Service) IAM policy gaps between OpenShift versions.
  Use when comparing AWS STS policies across OpenShift versions.
  Identifies new permissions, removed permissions, and changed permission scopes.
  Exits 0 when validation passes, exits 1 when validation fails or on execution error.
  Automatically generates comprehensive reports in HTML and JSON formats.
compatibility:
  required_tools:
    - python3
    - oc (OpenShift CLI - for extracting credential requests)
    - jq (for JSON processing)
    - PyYAML (for YAML processing)
---

# AWS STS Policy Gap Analysis

Analyze differences in AWS STS IAM policies between two OpenShift versions.

## When to Use This Skill

Trigger this skill when:
- Comparing STS policies between OpenShift versions (e.g., 4.21 → 4.22)
- Analyzing permission changes for AWS-based managed OpenShift
- Planning version upgrades and need to understand IAM permission changes
- Investigating STS-related issues or permission requirements
- CI/CD pipelines that need to detect policy changes

## What This Skill Does

1. **Extracts credential requests** from OpenShift release payloads using `oc adm release extract`
2. **Converts CredentialsRequest manifests** to consolidated IAM policy JSON documents
3. **Compares IAM permissions** at action-level and service-level to identify changes
4. **Validates policy files** against OCP release credential requests using **per-file comparison** (aggregates all permission changes across individual CRs, not just globally-new permissions); exits 1 if validation fails (CHECK #1 or #2) or on execution failures

## Workflow

### Step 1: Understand the Request

Parse the comparison request to identify:
- Baseline version (default: auto-detect latest stable, e.g., `4.21.6`)
- Target version (default: auto-detect latest candidate, e.g., `4.22.0-ec.3`)
- Specific focus areas (if any)

### Step 2: Run the Gap Analysis Script

Execute the `scripts/gap-aws-sts.py` Python script:

**Auto-detect versions (recommended):**
```bash
# Compares latest stable → latest candidate
python3 ./scripts/gap-aws-sts.py

# Use nightly as target
TARGET_VERSION=NIGHTLY python3 ./scripts/gap-aws-sts.py

# Custom report directory
python3 ./scripts/gap-aws-sts.py --report-dir /custom/reports
```

**Explicit versions:**
```bash
python3 ./scripts/gap-aws-sts.py \
  --baseline <version> \
  --target <version> \
  [--report-dir <path>] \
  [--verbose]

# Examples
python3 ./scripts/gap-aws-sts.py --baseline 4.21.6 --target 4.22.0-ec.3
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
```

**Environment variables:**
```bash
# Override versions
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 python3 ./scripts/gap-aws-sts.py

# Use nightly
TARGET_VERSION=NIGHTLY python3 ./scripts/gap-aws-sts.py

# Custom report location
REPORT_DIR=/ci-artifacts python3 ./scripts/gap-aws-sts.py
```

**Generated Reports:**
```bash
reports/gap-analysis-aws-sts_4.21.6_to_4.22.0-ec.3_20260325_120000.html  # HTML
reports/gap-analysis-aws-sts_4.21.6_to_4.22.0-ec.3_20260325_120000.json  # JSON
```

Note: Platform is always 'aws' for this script.

**The script performs these steps automatically:**
1. Validates prerequisites (jq, oc CLI availability)
2. Extracts credential requests from both versions using `oc adm release extract --credentials-requests --cloud=aws`
3. Parses YAML CredentialsRequest manifests and converts to IAM policy JSON
4. Compares policies at action-level and service-level
5. Validates policy files against OCP release; exits 1 if validation fails, exits 0 if validation passes

**Exit Codes:**
- `0`: Validation PASSED (CHECK #1 and CHECK #2 both valid)
- `1`: Validation FAILED (CHECK #1 or CHECK #2 failed) OR execution failure (e.g., missing tools, network errors, invalid versions)

**This uses the same approach as osdctl** for data extraction.

### Step 3: Interpret Results

The script exits based on validation result:
- **Exit 0**: Validation PASSED (all policy files are present and match OCP release)
- **Exit 1**: Validation FAILED (CHECK #1 or CHECK #2 failed) or execution error (missing tools, network errors, invalid versions)

**For detailed analysis**, examine the generated JSON reports in the reports directory, or re-run the analysis with `--verbose` for detailed per-file output.

## Output Format

The script outputs log messages to stderr and exits based on validation result:

```
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Fetching baseline STS policy...
[INFO] Extracting credential requests from quay.io/openshift-release-dev/ocp-release:4.21-x86_64 for cloud=aws
[SUCCESS] Credential requests extracted to: /tmp/ocp-crs-XXXXXX
[INFO] Processing 7 credential request file(s)...
[SUCCESS] Converted to IAM policy: 10 unique statement(s)
[SUCCESS] Successfully extracted STS policy
[INFO] Fetching target STS policy...
[SUCCESS] Successfully extracted STS policy
[INFO] Comparing STS policies...
[INFO] Policy differences detected: 3 added, 1 removed
```

Exit code: `0` (validation PASSED) or `1` (validation FAILED - CHECK #1 or #2)

Or:

```
[SUCCESS] No policy differences found between 4.21 and 4.22
```

Exit code: `0` (validation PASSED, no differences)

## Important Considerations

- **Security focus**: Highlight any permissions with broad scopes or security implications
- **Customer impact**: Note if changes require customer action (IAM role updates)
- **Backward compatibility**: Identify if old permissions are still supported
- **Service account changes**: Track changes to OIDC providers or service accounts

## Going Beyond the Script

The script provides a simple pass/fail check. For detailed analysis, you can:

**Extract Detailed Comparison Data:**
The script automatically generates JSON reports with structured comparison data:
```bash
# Run analysis to generate reports
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22

# Extract specific data from JSON report
jq '.comparison.actions.target_only' reports/gap-analysis-aws-sts_*.json  # Added actions
jq '.comparison.actions.baseline_only' reports/gap-analysis-aws-sts_*.json  # Removed actions
jq '.comparison.actions.common' reports/gap-analysis-aws-sts_*.json  # Unchanged actions

# Open HTML report in browser
firefox reports/gap-analysis-aws-sts_*.html
```

**Context and Explanation:**
- Explain *why* permissions changed (link to features, bug fixes, enhancement proposals)
- Connect changes to release notes and known issues
- Identify patterns in permission evolution across versions

**Security Analysis:**
- Assess security posture improvements or regressions
- Highlight permissions with broad scopes (e.g., `Resource: "*"`)
- Flag potentially risky new permissions (e.g., IAM write permissions)
- Recommend least-privilege alternatives when applicable

**Customer Impact:**
- Identify if changes require customer action (IAM role updates)
- Provide step-by-step migration guides for complex changes
- Estimate upgrade impact (breaking changes vs. transparent)
- Suggest pre-upgrade validation steps

**CI/CD Integration:**
- Use exit codes directly: exit 1 means validation failed (CHECK #1 or CHECK #2)
- Script exits 0 only when all validation checks pass
- Parse JSON reports for detailed per-check results

## osdctl Integration

This skill uses the **same underlying approach as osdctl** for data extraction:

```bash
# osdctl command (simple file diff)
osdctl iampermissions diff -c aws -b 4.21.0 -t 4.22.0

# Our validation-based check (for CI/CD)
python3 ./scripts/gap-aws-sts.py --baseline 4.21.0 --target 4.22.0
echo $?  # 0 = validation PASSED, 1 = validation FAILED or execution error
```

**What's the same:**
- Both use `oc adm release extract --credentials-requests --cloud=aws`
- Both extract from the same OpenShift release payloads on quay.io
- Both process the same CredentialsRequest YAML files

**What gap-analysis adds:**
- Consolidates CredentialsRequests into unified IAM policy documents
- Performs structured action-level and service-level comparison
- Provides CI/CD-friendly exit codes for automation
- Can be extended to generate detailed reports when needed

## Example Interaction

**User**: "Check if AWS STS policies changed between latest stable and latest candidate"

**Response**:
```bash
# Execute the gap analysis with auto-detection
python3 ./scripts/gap-aws-sts.py
# Reports generated in: ./reports/
```

**User**: "Check if AWS STS policies changed between OpenShift 4.21 and 4.22"

**Response**:
```bash
# Execute the gap analysis
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22 --verbose
# View results: firefox reports/gap-analysis-aws-sts_*.html
```

**User**: "Check AWS STS policies against latest nightly"

**Response**:
```bash
# Execute with nightly target
TARGET_VERSION=NIGHTLY python3 ./scripts/gap-aws-sts.py
# Review HTML report: firefox reports/gap-analysis-aws-sts_*.html
```

**What happens:**
1. Script validates prerequisites (jq, oc CLI)
2. Extracts credential requests from 4.21 release image using `oc adm release extract`
   - Processes 7 credential request YAML files
   - Converts to consolidated IAM policy with ~10 unique statements
3. Extracts credential requests from 4.22 release image
   - Processes 7 credential request YAML files
   - Converts to consolidated IAM policy with ~10 unique statements
4. Compares policies at action-level and service-level
5. Exits with code based on results

**Sample Output (differences found):**
```
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Fetching baseline STS policy...
[SUCCESS] Successfully extracted STS policy
[INFO] Fetching target STS policy...
[SUCCESS] Successfully extracted STS policy
[INFO] Comparing STS policies...
[INFO] Policy differences detected: 3 added, 1 removed
```
Exit code: `0` (validation PASSED) or `1` (validation FAILED)

**Sample Output (no differences):**
```
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[SUCCESS] No policy differences found between 4.21 and 4.22
```
Exit code: `0` (validation PASSED)

**Use in CI/CD:**
```bash
# Exit code reflects validation result: 0=PASSED, 1=FAILED
if python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22; then
  echo "Validation passed - safe to proceed"
else
  echo "Validation failed - policy files missing or outdated"
fi

# Use JSON report for programmatic analysis
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
if jq -e '.comparison.actions.target_only | length > 0' reports/gap-analysis-aws-sts_*.json >/dev/null 2>&1; then
  echo "New permissions detected"
fi
```

## Practical Tips

**Version Detection:**
- **Auto-detect (recommended)**: No flags needed, compares latest stable → latest candidate
- **Environment variables**: `BASE_VERSION` and `TARGET_VERSION` for CI/CD pipelines
- **Special keywords**: `TARGET_VERSION=NIGHTLY` for nightly builds, `TARGET_VERSION=CANDIDATE` for explicit candidate

**Version Format:**
- Use full version numbers: `4.21.6` or `4.22.0-ec.3`
- Major.minor works too: `4.21`, `4.22`
- Candidate versions: `4.22.0-ec.3`, `4.22.0-rc.1`
- Nightly versions: `4.22.0-0.nightly-2026-03-15-203841`
- Full pullspecs also supported

**Troubleshooting:**
- If `oc adm release extract` fails, the version may not exist
- Verify version exists: `oc adm release info quay.io/openshift-release-dev/ocp-release:X.Y.Z-x86_64`
- Use `--verbose` flag to see detailed extraction progress
- Ensure `oc` CLI is installed and accessible
- Auto-detection requires `curl` and `jq` for querying release APIs

**Platform:**
- This script analyzes AWS STS policies only (platform is always 'aws')
- Works for all AWS-based OpenShift deployments (OSD, ROSA Classic, ROSA HCP)

**Performance:**
- Auto-detection: 2-5 seconds for version queries
- First-time extraction: 20-60 seconds per version (network-dependent)
- Most time spent downloading release image metadata

**Validation:**
- Always cross-check with osdctl when possible
- Review the raw JSON files in the temp directory if results seem unexpected
- Compare across multiple version pairs to identify patterns
- Auto-detected versions include validation (stable→GA, candidate→dev)
