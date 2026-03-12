---
name: gcp-wif-gap
description: >
  Analyze GCP Workload Identity Federation (WIF) policy gaps between OpenShift versions.
  Use when comparing WIF configurations, IAM roles, and service account permissions
  across OpenShift versions.
  Exits with code 0 if no differences, code 1 if differences found.
compatibility:
  required_tools:
    - bash
    - oc (OpenShift CLI - for extracting credential requests)
    - jq (for JSON processing)
    - yq or python3 with PyYAML (for YAML parsing)
---

# GCP WIF Policy Gap Analysis

Analyze differences in GCP Workload Identity Federation policies between OpenShift versions.

## When to Use

- Comparing WIF policies between versions
- Planning GCP-based upgrades
- Investigating WIF permission issues
- Understanding service account changes
- CI/CD pipelines that need to detect policy changes

## Workflow

1. Parse baseline and target versions (e.g., `4.21` → `4.22`)
2. Extract credential requests from release payloads using `oc adm release extract --cloud=gcp`
3. Convert CredentialsRequest YAML manifests to GCP IAM policy format
4. Compare IAM roles, permissions, and service account bindings
5. Exit with code 0 if no differences, code 1 if differences detected

## Script Usage

```bash
./scripts/gap-gcp-wif.sh \
  --baseline <version> \
  --target <version> \
  [--verbose]
```

**Example:**
```bash
./scripts/gap-gcp-wif.sh \
  --baseline 4.21 \
  --target 4.22 \
  --verbose
```

**Exit Codes:**
- `0`: No policy differences found
- `1`: Policy differences detected

Note: Platform is always 'gcp' for this script.

## Key Focus Areas

- **IAM Roles**: New or removed GCP IAM roles
- **Permissions**: Individual permission changes within roles
- **Service Accounts**: Changes to GCP service account configurations
- **Workload Identity Pools**: Pool and provider configuration changes
- **Bindings**: Service account to Kubernetes service account bindings

## Output

The script outputs log messages to stderr and exits with appropriate code:

```
[INFO] Starting GCP WIF Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Fetching baseline WIF policy...
[SUCCESS] Successfully extracted WIF policy
[INFO] Fetching target WIF policy...
[SUCCESS] Successfully extracted WIF policy
[INFO] Comparing WIF policies...
[WARNING] Policy differences detected: 5 added, 2 removed
```

Exit code: `1` (differences found)

Or:

```
[SUCCESS] No policy differences found between 4.21 and 4.22
```

Exit code: `0` (no differences)

**Use in CI/CD:**
```bash
if ./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22; then
  echo "No policy changes - safe to proceed"
else
  echo "Policy changes detected - review required"
  exit 1
fi
```

## Going Beyond the Script

The script provides a simple pass/fail check. For detailed analysis, you can:

**Extract Detailed Comparison Data:**
If you need to analyze what changed, you can run the comparison functions manually:
```bash
# Extract policies to temp files
baseline_policy=$(mktemp)
target_policy=$(mktemp)

# Get policies (using functions from the script)
source scripts/lib/common.sh
source scripts/gap-gcp-wif.sh
get_wif_policy "4.21" > "$baseline_policy"
get_wif_policy "4.22" > "$target_policy"

# Compare and examine results
compare_sts_policies "$baseline_policy" "$target_policy" | jq '.'
```

**Context and Explanation:**
- Explain why WIF permissions changed
- Connect changes to OpenShift features and enhancements
- Identify patterns across versions

**Security Analysis:**
- Assess security posture changes
- Highlight permissions with broad scopes
- Recommend least-privilege alternatives

**Customer Impact:**
- Identify if changes require customer action
- Provide migration guides for complex changes
- Suggest pre-upgrade validation steps

**CI/CD Integration:**
- Use the exit code in CI pipelines to detect policy changes
- Block deployments if unexpected policy changes occur
- Automate notifications when policies differ
