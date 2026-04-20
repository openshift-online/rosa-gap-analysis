---
name: ocp-gate-ack-gap
description: >
  Analyze OCP admin gate acknowledgments for upgrade readiness.
  Verifies that admin gates from baseline version are properly acknowledged in target version.
  Identifies missing acknowledgment files or unacknowledged gates that would block upgrades.
  Automatically generates comprehensive reports in HTML and JSON formats.
compatibility:
  required_tools:
    - python3
    - curl (for GitHub API access)
    - PyYAML (for YAML processing)
---

# OCP Admin Gate Acknowledgment Analysis

Verify that admin gates from the baseline OpenShift version are properly acknowledged in the target version's managed-cluster-config.

## When to Use

- Planning managed cluster upgrades (OSD, ROSA)
- Validating upgrade readiness
- Identifying missing acknowledgment files
- Detecting unacknowledged admin gates that would block upgrades
- CI/CD pipelines that need to verify upgrade prerequisites

## Workflow

1. Parse baseline and target versions (default: auto-detect latest stable → latest candidate)
2. Fetch admin gate ConfigMap from cluster-version-operator repo (baseline version)
3. Check if admin gates exist in the ConfigMap's `data` field
4. Fetch admin acknowledgment ConfigMap from managed-cluster-config repo (target version)
5. Validate acknowledgment structure based on gate presence:
   - **If gates exist**: Both `config.yaml` AND `admin-ack.yaml` MUST be present, all gates must be acknowledged
   - **If no gates**: Both files MUST be absent (directory should not exist)
6. Report upgrade readiness status and generate detailed reports

## Script Usage

**Auto-detect versions (recommended):**
```bash
# Compares latest stable → latest candidate
python3 ./scripts/gap-ocp-gate-ack.py

# With verbose output
python3 ./scripts/gap-ocp-gate-ack.py --verbose

# Custom report directory
python3 ./scripts/gap-ocp-gate-ack.py --report-dir /custom/reports
```

**Explicit versions:**
```bash
python3 ./scripts/gap-ocp-gate-ack.py \
  --baseline <version> \
  --target <version> \
  [--report-dir <path>] \
  [--verbose]
```

**Examples:**
```bash
# Auto-detect
python3 ./scripts/gap-ocp-gate-ack.py

# Explicit versions (uses minor versions: 4.21, 4.22)
python3 ./scripts/gap-ocp-gate-ack.py --baseline 4.21 --target 4.22

# With verbose output
python3 ./scripts/gap-ocp-gate-ack.py --baseline 4.21.7 --target 4.22.0 --verbose

# Environment variables
BASE_VERSION=4.21 TARGET_VERSION=4.22 python3 ./scripts/gap-ocp-gate-ack.py

# Custom report location
REPORT_DIR=/ci-artifacts python3 ./scripts/gap-ocp-gate-ack.py
```

**Generated Reports:**
```bash
reports/gap-analysis-ocp-gate-ack_4.21_to_4.22_20260327_120000.html  # HTML
reports/gap-analysis-ocp-gate-ack_4.21_to_4.22_20260327_120000.json  # JSON
```

**Exit Codes:**
- `0`: Validation PASSED (CHECK #5 valid - all gates acknowledged or no gates required)
- `1`: Validation FAILED (CHECK #5 failed - missing acknowledgment file or unacknowledged gates) OR execution failure (e.g., missing tools, network errors, invalid versions)

**Version Resolution:**
- CLI flags > Environment variables > Auto-detect
- Auto-detect: latest stable (baseline) → latest candidate (target)
- Uses minor versions (4.21, 4.22) for file lookups

## Key Validation Checks

1. **Admin Gates Existence**: Checks baseline version for admin gates
2. **Acknowledgment Structure** (conditional):
   - **If gates exist**: Both `config.yaml` AND `admin-ack.yaml` must be present
   - **If no gates**: Both files must be absent
3. **Gate Acknowledgments**: When gates exist, ensures all baseline gates are acknowledged in target
4. **Config Validation**: When files exist, validates `config.yaml` has correct baseline version
5. **Extra Acknowledgments**: Reports any extra acknowledgments (informational)

## Upgrade Readiness States

### ✅ UPGRADE READY
**Scenario 1: No gates in baseline**
- No admin gates exist in baseline version
- Both `config.yaml` and `admin-ack.yaml` are absent in target directory
- Acknowledgment directory correctly does not exist

**Scenario 2: Gates exist and acknowledged**
- Admin gates exist in baseline version
- Both `config.yaml` and `admin-ack.yaml` are present in target directory
- All admin gates are properly acknowledged in `admin-ack.yaml`
- `config.yaml` has correct baseline version reference

### ❌ UPGRADE NOT READY (Blocked)
**Structure validation failures:**
- **Gates exist but files missing**: Gates in baseline but `config.yaml` or `admin-ack.yaml` missing
- **No gates but files present**: No gates in baseline but `config.yaml` or `admin-ack.yaml` exist
- **Partial structure**: Only one file present (both must be present together or absent together)

**Content validation failures:**
- **Unacknowledged Gates**: One or more gates exist in baseline but not acknowledged in target
- **Invalid config.yaml**: Baseline version mismatch or structural errors

## Output

The script outputs log messages and exits based on validation result:

**No admin gates (upgrade ready):**
```
[INFO] Starting OCP Admin Gate Acknowledgment Analysis
[INFO] Baseline version: 4.21 (minor: 4.21)
[INFO] Target version: 4.22 (minor: 4.22)
[INFO] Fetching admin gates from cluster-version-operator...
[INFO] No admin gates found for version 4.21
[SUCCESS] No admin gates in 4.21, upgrade to 4.22 requires no acknowledgments
```

Exit code: `0` (validation PASSED, upgrade ready)

**Gates acknowledged (upgrade ready):**
```
[INFO] Starting OCP Admin Gate Acknowledgment Analysis
[INFO] Baseline version: 4.20 (minor: 4.20)
[INFO] Target version: 4.21 (minor: 4.21)
[INFO] Fetching admin gates from cluster-version-operator...
[SUCCESS] Found 2 admin gate(s) for version 4.20
[INFO] Fetching admin acknowledgments from managed-cluster-config...
[SUCCESS] Found 2 acknowledgment(s) for version 4.21
[INFO] Analyzing gate acknowledgments...
[SUCCESS] ✅ 2 gate(s) properly acknowledged
  - ack-4.20-example-gate-1
  - ack-4.20-example-gate-2
[SUCCESS] ✅ UPGRADE READY: All gates acknowledged for 4.20 → 4.21
```

Exit code: `0` (validation PASSED, upgrade ready)

**Acknowledgment file missing (upgrade blocked):**
```
[INFO] Starting OCP Admin Gate Acknowledgment Analysis
[INFO] Baseline version: 4.20 (minor: 4.20)
[INFO] Target version: 4.21 (minor: 4.21)
[INFO] Fetching admin gates from cluster-version-operator...
[SUCCESS] Found 2 admin gate(s) for version 4.20
[INFO] Fetching admin acknowledgments from managed-cluster-config...
[WARNING] Admin acknowledgment ConfigMap not found for version 4.21
[ERROR] ❌ UPGRADE BLOCKED: Acknowledgment file missing for 4.21
[ERROR]    Required file: deploy/osd-cluster-acks/ocp/4.21/admin-ack.yaml
[ERROR] ❌ UPGRADE NOT READY: 4.20 → 4.21
```

Exit code: `1` (validation FAILED - CHECK #5, upgrade not ready)

**Unacknowledged gates (upgrade blocked):**
```
[INFO] Starting OCP Admin Gate Acknowledgment Analysis
[INFO] Baseline version: 4.20 (minor: 4.20)
[INFO] Target version: 4.21 (minor: 4.21)
[INFO] Fetching admin gates from cluster-version-operator...
[SUCCESS] Found 3 admin gate(s) for version 4.20
[INFO] Fetching admin acknowledgments from managed-cluster-config...
[SUCCESS] Found 2 acknowledgment(s) for version 4.21
[INFO] Analyzing gate acknowledgments...
[SUCCESS] ✅ 2 gate(s) properly acknowledged
  - ack-4.20-example-gate-1
  - ack-4.20-example-gate-2
[ERROR] ❌ UPGRADE BLOCKED: 1 gate(s) not acknowledged
  - ack-4.20-missing-gate
[ERROR] ❌ UPGRADE NOT READY: 4.20 → 4.21
```

Exit code: `1` (validation FAILED - CHECK #5, upgrade not ready)

## Data Sources

**Admin Gates (Baseline):**
- Repository: `openshift/cluster-version-operator`
- Branch: `release-{version}` (e.g., `release-4.21`)
- File: `install/0000_00_cluster-version-operator_01_admingate_configmap.yaml`
- URL: https://github.com/openshift/cluster-version-operator/blob/release-4.21/install/0000_00_cluster-version-operator_01_admingate_configmap.yaml

**Admin Acknowledgments (Target):**
- Repository: `openshift/managed-cluster-config`
- Branch: `master`
- File: `deploy/osd-cluster-acks/ocp/{version}/admin-ack.yaml` (e.g., `4.22`)
- URL: https://github.com/openshift/managed-cluster-config/blob/master/deploy/osd-cluster-acks/ocp/4.22/admin-ack.yaml

## Use in CI/CD

```bash
# Exit code reflects validation result: 0=PASSED, 1=FAILED
if python3 ./scripts/gap-ocp-gate-ack.py --baseline 4.20 --target 4.21; then
  echo "✅ Upgrade ready"
else
  echo "❌ Upgrade blocked - check reports for details"
fi

# Use JSON report for programmatic analysis
python3 ./scripts/gap-ocp-gate-ack.py --baseline 4.20 --target 4.21
if jq -e '.summary.upgrade_ready == false' reports/gap-analysis-ocp-gate-ack_*.json >/dev/null 2>&1; then
  echo "❌ Upgrade not ready"
  jq -r '.analysis.unacknowledged_gates[]' reports/gap-analysis-ocp-gate-ack_*.json
  exit 1
fi
```

## Remediation Actions

**If acknowledgment file is missing:**
1. Create file: `deploy/osd-cluster-acks/ocp/{target_version}/admin-ack.yaml`
2. Add acknowledgments for all required gates from baseline
3. Submit PR to `openshift/managed-cluster-config`

**If gates are unacknowledged:**
1. Add missing gate acknowledgments to existing file
2. Ensure gate names match exactly (case-sensitive)
3. Submit PR to `openshift/managed-cluster-config`

**Example acknowledgment file structure:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: admin-acks
  namespace: openshift-managed-upgrade-operator
data:
  ack-4.20-example-gate: "true"
  ack-4.20-another-gate: "true"
```

## Going Beyond the Script

**Manual verification:**
```bash
# Check baseline admin gates
curl -s "https://raw.githubusercontent.com/openshift/cluster-version-operator/release-4.20/install/0000_00_cluster-version-operator_01_admingate_configmap.yaml"

# Check target acknowledgments
curl -s "https://raw.githubusercontent.com/openshift/managed-cluster-config/master/deploy/osd-cluster-acks/ocp/4.21/admin-ack.yaml"
```

**Understanding Admin Gates:**
- Admin gates are safety mechanisms that require explicit acknowledgment before upgrades
- They typically indicate breaking changes or important notices
- Managed clusters (OSD/ROSA) require acknowledgment in managed-cluster-config
- Self-managed clusters can acknowledge via oc CLI

**Integration with Full Gap Analysis:**
- When run via `./scripts/gap-all.sh`, this check is included automatically
- Combined report includes OCP gate acknowledgment status
- Helps ensure comprehensive upgrade readiness validation
