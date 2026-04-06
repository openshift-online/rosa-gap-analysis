---
name: aws-sts-gap
description: >
  Analyze AWS STS (Security Token Service) IAM policy gaps between OpenShift versions.
  Use when comparing AWS STS policies across OpenShift versions.
  Identifies new permissions, removed permissions, and changed permission scopes.
  Logs detected policy differences but always exits 0 on successful execution.
  Automatically generates comprehensive reports in Markdown, HTML, and JSON formats.
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
4. **Logs policy differences** and always exits 0 on successful execution (only exits 1 on execution failures)

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
reports/gap-analysis-aws-sts_4.21.6_to_4.22.0-ec.3_20260325_120000.md    # Markdown
reports/gap-analysis-aws-sts_4.21.6_to_4.22.0-ec.3_20260325_120000.html  # HTML
reports/gap-analysis-aws-sts_4.21.6_to_4.22.0-ec.3_20260325_120000.json  # JSON
```

Note: Platform is always 'aws' for this script.

**The script performs these steps automatically:**
1. Validates prerequisites (jq, oc CLI availability)
2. Extracts credential requests from both versions using `oc adm release extract --credentials-requests --cloud=aws`
3. Parses YAML CredentialsRequest manifests and converts to IAM policy JSON
4. Compares policies at action-level and service-level
5. Logs detected differences and always exits 0 on successful execution

**Exit Codes:**
- `0`: Successful execution (regardless of whether differences were found)
- `1`: Execution failure (e.g., missing tools, network errors, invalid versions)

**This uses the same approach as osdctl** for data extraction.

### Step 3: Data Extraction (Automated)

The script uses `oc adm release extract` to extract credential requests:

**oc adm release extract** (Same as osdctl)
- Directly extracts CredentialsRequest manifests from release image payloads on quay.io
- Command: `oc adm release extract quay.io/openshift-release-dev/ocp-release:X.Y.Z-x86_64 --credentials-requests --cloud=aws`
- Official, authoritative source - guaranteed to match the actual release
- Requires: `oc` CLI installed and accessible

### Step 4: Policy Conversion and Comparison

**Policy Conversion:**
The script converts CredentialsRequest YAML manifests to IAM policy JSON:
- Parses `spec.providerSpec.statementEntries` from each CredentialsRequest
- Normalizes lowercase keys (`effect`, `action`, `resource`) to IAM format (`Effect`, `Action`, `Resource`)
- Consolidates all statements into a unified policy document
- Removes duplicate statements

**Typical Credential Request Files Processed:**
1. `0000_30_cluster-api_01_credentials-request.yaml` - Cluster API operations
2. `0000_30_machine-api-operator_00_credentials-request.yaml` - Machine/node management
3. `0000_50_cloud-credential-operator_05-iam-ro-credentialsrequest.yaml` - IAM read-only
4. `0000_50_cluster-image-registry-operator_01-registry-credentials-request.yaml` - Image registry
5. `0000_50_cluster-ingress-operator_00-ingress-credentials-request.yaml` - Ingress/load balancers
6. `0000_50_cluster-network-operator_02-cncc-credentials.yaml` - Networking
7. `0000_50_cluster-storage-operator_03_credentials_request_aws.yaml` - Storage volumes

**Comparison Analysis:**
- **Action-level changes**: Specific IAM permissions added/removed (e.g., `ec2:CreateTags`)
- **Service-level changes**: New/removed AWS service integrations (e.g., new `elasticloadbalancing` service)
- **Resource scope changes**: Changes to resource ARNs or wildcards
- **Statement deduplication**: Automatic cleanup to avoid false positives

### Step 5: Interpret Results

The script always exits with code 0 on successful execution and logs:
- Number of added permissions (if any)
- Number of removed permissions (if any)
- Summary message indicating result

The script only exits with code 1 on execution failures:
- Missing required tools (jq, oc CLI)
- Network errors fetching release images
- Invalid version strings
- Other execution errors

**For detailed analysis**, you can examine the temporary comparison files before they're cleaned up by adding custom logic, or re-run the analysis with the `compare_sts_policies` function from `scripts/lib/common.sh`.

## Output Format

The script outputs log messages to stderr and always exits 0 on successful execution:

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

Exit code: `0` (successful execution, differences found)

Or:

```
[SUCCESS] No policy differences found between 4.21 and 4.22
```

Exit code: `0` (successful execution, no differences)

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

# View human-readable report
cat reports/gap-analysis-aws-sts_*.md

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
- Parse script output to detect policy changes (exit codes only indicate execution success/failure)
- Script always exits 0 on successful execution regardless of differences
- Automate notifications when policies differ by parsing log messages

## osdctl Integration

This skill uses the **same underlying approach as osdctl** for data extraction:

```bash
# osdctl command (simple file diff)
osdctl iampermissions diff -c aws -b 4.21.0 -t 4.22.0

# Our exit-code based check (for CI/CD)
./scripts/gap-aws-sts.sh --baseline 4.21.0 --target 4.22.0
echo $?  # 0 = no changes, 1 = changes detected
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
# View results: cat reports/gap-analysis-aws-sts_*.md
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
Exit code: `0` (successful execution)

**Sample Output (no differences):**
```
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[SUCCESS] No policy differences found between 4.21 and 4.22
```
Exit code: `0` (successful execution)

**Use in CI/CD:**
```bash
# Script always exits 0 on success
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22

# Check for differences by parsing output
if python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22 2>&1 | grep -q "Policy differences detected"; then
  echo "Policy changes detected - review reports/"
else
  echo "No policy changes - safe to proceed"
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
