---
name: gcp-wif-gap
description: >
  Analyze GCP Workload Identity Federation (WIF) policy gaps between OpenShift versions.
  Use when comparing WIF configurations, IAM roles, and service account permissions
  across OpenShift versions.
  Exits 0 when validation passes, exits 1 when validation fails or on execution error.
  Automatically generates comprehensive reports in HTML and JSON formats.
compatibility:
  required_tools:
    - python3
    - oc (OpenShift CLI - for extracting credential requests)
    - jq (for JSON processing)
    - PyYAML (for YAML processing)
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

1. Parse baseline and target versions (default: auto-detect latest stable → latest candidate)
2. Extract credential requests from release payloads using `oc adm release extract --cloud=gcp`
3. Convert CredentialsRequest YAML manifests to GCP IAM policy format
4. Compare IAM roles, permissions, and service account bindings
5. Validate WIF templates against OCP release using **per-file comparison** (aggregates all permission changes across individual CRs, not just globally-new permissions); exit 1 if validation fails (CHECK #3 or CHECK #4), exit 0 if validation passes

## Script Usage

**Auto-detect versions (recommended):**
```bash
# Compares latest stable → latest candidate
python3 ./scripts/gap-gcp-wif.py

# Use nightly as target
TARGET_VERSION=NIGHTLY python3 ./scripts/gap-gcp-wif.py

# Custom report directory
python3 ./scripts/gap-gcp-wif.py --report-dir /custom/reports
```

**Explicit versions:**
```bash
python3 ./scripts/gap-gcp-wif.py \
  --baseline <version> \
  --target <version> \
  [--report-dir <path>] \
  [--verbose]
```

**Examples:**
```bash
# Auto-detect
python3 ./scripts/gap-gcp-wif.py

# Explicit versions
python3 ./scripts/gap-gcp-wif.py --baseline 4.21 --target 4.22 --verbose

# Full version strings
python3 ./scripts/gap-gcp-wif.py --baseline 4.21.6 --target 4.22.0-ec.3

# Environment variables
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 python3 ./scripts/gap-gcp-wif.py

# Use nightly
TARGET_VERSION=NIGHTLY python3 ./scripts/gap-gcp-wif.py

# Custom report location
REPORT_DIR=/ci-artifacts python3 ./scripts/gap-gcp-wif.py
```

**Generated Reports:**
```bash
reports/gap-analysis-gcp-wif_4.21_to_4.22_20260325_120000.html  # HTML
reports/gap-analysis-gcp-wif_4.21_to_4.22_20260325_120000.json  # JSON
```

**Exit Codes:**
- `0`: Validation PASSED (CHECK #3 and CHECK #4 both valid)
- `1`: Validation FAILED (CHECK #3 or CHECK #4 failed) OR execution failure (e.g., missing tools, network errors, invalid versions)

**Version Resolution:**
- CLI flags > Environment variables > Auto-detect
- Auto-detect: latest stable (baseline) → latest candidate (target)
- Special keywords: `TARGET_VERSION=NIGHTLY` or `TARGET_VERSION=CANDIDATE`

Note: Platform is always 'gcp' for this script.

## Key Focus Areas

- **IAM Roles**: New or removed GCP IAM roles
- **Permissions**: Individual permission changes within roles
- **Service Accounts**: Changes to GCP service account configurations
- **Workload Identity Pools**: Pool and provider configuration changes
- **Bindings**: Service account to Kubernetes service account bindings

## Output

The script outputs log messages to stderr and exits based on validation result:

```
[INFO] Starting GCP WIF Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Fetching baseline WIF policy...
[SUCCESS] Successfully extracted WIF policy
[INFO] Fetching target WIF policy...
[SUCCESS] Successfully extracted WIF policy
[INFO] Comparing WIF policies...
[INFO] Policy differences detected: 5 added, 2 removed
```

Exit code: `0` (validation PASSED) or `1` (validation FAILED - CHECK #3 or #4)

Or:

```
[SUCCESS] No policy differences found between 4.21 and 4.22
```

Exit code: `0` (validation PASSED, no differences)

**Use in CI/CD:**
```bash
# Exit code reflects validation result: 0=PASSED, 1=FAILED
if python3 ./scripts/gap-gcp-wif.py --baseline 4.21 --target 4.22; then
  echo "Validation passed - safe to proceed"
else
  echo "Validation failed - WIF templates missing or outdated"
fi

# Use JSON report for programmatic analysis
python3 ./scripts/gap-gcp-wif.py --baseline 4.21 --target 4.22
if jq -e '.comparison.actions.target_only | length > 0' reports/gap-analysis-gcp-wif_*.json >/dev/null 2>&1; then
  echo "New permissions detected"
fi
```

## Going Beyond the Script

The script provides a simple pass/fail check. For detailed analysis, you can:

**Extract Detailed Comparison Data:**
The script automatically generates JSON reports with structured comparison data:
```bash
# Run analysis to generate reports
python3 ./scripts/gap-gcp-wif.py --baseline 4.21 --target 4.22

# Extract specific data from JSON report
jq '.comparison.actions.target_only' reports/gap-analysis-gcp-wif_*.json  # Added permissions
jq '.comparison.actions.baseline_only' reports/gap-analysis-gcp-wif_*.json  # Removed permissions
jq '.comparison.actions.common' reports/gap-analysis-gcp-wif_*.json  # Unchanged permissions

# Open HTML report in browser
firefox reports/gap-analysis-gcp-wif_*.html
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
- Use exit codes directly: exit 1 means validation failed (CHECK #3 or CHECK #4)
- Script exits 0 only when all validation checks pass
- Parse JSON reports for detailed per-check results
