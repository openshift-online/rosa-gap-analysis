---
name: aws-sts-gap
description: >
  Analyze AWS STS (Security Token Service) IAM policy gaps between OpenShift versions.
  Use when comparing AWS STS policies across OpenShift versions.
  Identifies new permissions, removed permissions, and changed permission scopes.
  Exits with code 0 if no differences, code 1 if differences found.
compatibility:
  required_tools:
    - bash
    - oc (OpenShift CLI - for extracting credential requests)
    - jq (for JSON processing)
    - yq or python3 with PyYAML (for YAML parsing)
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
4. **Returns exit code** indicating whether policy differences exist (0 = no changes, 1 = changes detected)

## Workflow

### Step 1: Understand the Request

Parse the comparison request to identify:
- Baseline version (e.g., `4.21.0`)
- Target version (e.g., `4.22.0`)
- Specific focus areas (if any)

### Step 2: Run the Gap Analysis Script

Execute the `scripts/gap-aws-sts.sh` script:

```bash
./scripts/gap-aws-sts.sh \
  --baseline <version> \
  --target <version> \
  [--verbose]
```

Note: Platform is always 'aws' for this script.

**The script performs these steps automatically:**
1. Validates prerequisites (jq, oc CLI availability)
2. Extracts credential requests from both versions using `oc adm release extract --credentials-requests --cloud=aws`
3. Parses YAML CredentialsRequest manifests and converts to IAM policy JSON
4. Compares policies at action-level and service-level
5. Exits with code 0 if no differences found, code 1 if differences detected

**Exit Codes:**
- `0`: No policy differences found
- `1`: Policy differences detected

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

The script exits with:
- **Exit code 0**: No policy differences found between baseline and target
- **Exit code 1**: Policy differences detected (permissions added or removed)

The script logs:
- Number of added permissions
- Number of removed permissions
- Summary message indicating result

**For detailed analysis**, you can examine the temporary comparison files before they're cleaned up by adding custom logic, or re-run the analysis with the `compare_sts_policies` function from `scripts/lib/common.sh`.

## Output Format

The script outputs log messages to stderr and exits with appropriate code:

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
[WARNING] Policy differences detected: 3 added, 1 removed
```

Exit code: `1` (differences found)

Or:

```
[SUCCESS] No policy differences found between 4.21 and 4.22
```

Exit code: `0` (no differences)

## Important Considerations

- **Security focus**: Highlight any permissions with broad scopes or security implications
- **Customer impact**: Note if changes require customer action (IAM role updates)
- **Backward compatibility**: Identify if old permissions are still supported
- **Service account changes**: Track changes to OIDC providers or service accounts

## Going Beyond the Script

The script provides a simple pass/fail check. For detailed analysis, you can:

**Extract Detailed Comparison Data:**
If you need to analyze what changed, you can run the comparison functions manually:
```bash
# Extract policies to temp files
baseline_policy=$(mktemp)
target_policy=$(mktemp)

# Get policies (using functions from the script)
get_sts_policy "4.21" > "$baseline_policy"
get_sts_policy "4.22" > "$target_policy"

# Compare and examine results
compare_sts_policies "$baseline_policy" "$target_policy" | jq '.'
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
- Use the exit code in CI pipelines to detect policy changes
- Block deployments if unexpected policy changes occur
- Automate notifications when policies differ

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

**User**: "Check if AWS STS policies changed between OpenShift 4.21 and 4.22"

**Response**:
```bash
# Execute the gap analysis
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22 --verbose
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
[WARNING] Policy differences detected: 3 added, 1 removed
```
Exit code: `1`

**Sample Output (no differences):**
```
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[SUCCESS] No policy differences found between 4.21 and 4.22
```
Exit code: `0`

**Use in CI/CD:**
```bash
if ./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22; then
  echo "No policy changes - safe to proceed"
else
  echo "Policy changes detected - review required"
  exit 1
fi
```

## Practical Tips

**Version Format:**
- Use full version numbers: `4.21.0` not `4.21`
- Include patch version for accurate results
- RC versions work: `4.22.0-rc.1`

**Troubleshooting:**
- If `oc adm release extract` fails, the version may not exist
- Verify version exists: `oc adm release info quay.io/openshift-release-dev/ocp-release:X.Y.Z-x86_64`
- Use `--verbose` flag to see detailed extraction progress
- Ensure `oc` CLI is installed and accessible

**Platform:**
- This script analyzes AWS STS policies only (platform is always 'aws')
- Works for all AWS-based OpenShift deployments (OSD, ROSA Classic, ROSA HCP)

**Performance:**
- First-time extraction: 20-60 seconds per version (network-dependent)
- Most time spent downloading release image metadata

**Validation:**
- Always cross-check with osdctl when possible
- Review the raw JSON files in the temp directory if results seem unexpected
- Compare across multiple version pairs to identify patterns
