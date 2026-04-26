# Validation Checks

The gap analysis framework performs 6 validation checks across all scripts.

## Check Numbering

All scripts use a consistent global check numbering system:

| Check # | Category | Description | Pass/Fail Impact |
|---------|----------|-------------|------------------|
| **1** | AWS STS Resources | Validates STS policy files exist in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `resources/sts/{version}/` and match OCP release changes (per-file comparison) | Exit code 1 on FAIL |
| **2** | AWS STS Admin Ack | Validates admin acknowledgment files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/sts/{version}/` | Exit code 1 on FAIL |
| **3** | GCP WIF Resources | Validates WIF template (vanilla.yaml) in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `resources/wif/{version}/` and matches OCP release changes (per-file comparison) | Exit code 1 on FAIL |
| **4** | GCP WIF Admin Ack | Validates admin acknowledgment files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/wif/{version}/` | Exit code 1 on FAIL |
| **5** | OCP Admin Gates | Validates admin gates from cluster-version-operator are acknowledged in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/ocp/{version}/` (conditional: if gates exist, both files required; if no gates, both files must be absent) | Exit code 1 on FAIL |
| **6** | Feature Gates | Analyzes feature gate changes from Sippy API (informational only) | Always PASS (exit code 0) |

## Check Execution by Script

### gap-aws-sts.py
- **Check 1:** AWS STS Resources Validation
- **Check 2:** AWS STS Admin Acknowledgment

### gap-gcp-wif.py
- **Check 3:** GCP WIF Resources Validation
- **Check 4:** GCP WIF Admin Acknowledgment

### gap-ocp-gate-ack.py
- **Check 5:** OCP Admin Gate Acknowledgments

### gap-feature-gates.py
- **Check 6:** Feature Gates Analysis (Informational)

### gap-all.sh (Combined)
Runs all checks in order:
1. AWS STS (Checks 1-2)
2. GCP WIF (Checks 3-4)
3. OCP Admin Gates (Check 5)
4. Feature Gates (Check 6) - Always executed last

## Output Format

All checks follow a consistent output format:

### Success Output
```
============================================================
✓ VALIDATION PASSED - All checks successful
============================================================

CHECK #X: [Check Name] [PASS]
  Location: https://github.com/openshift/managed-cluster-config/tree/master/...
  ✓ Details about what was validated
  ✓ Additional success information
```

### Failure Output
```
============================================================
✗ VALIDATION FAILED
============================================================

CHECK #X: [Check Name] [FAIL]
Location: https://github.com/openshift/managed-cluster-config/tree/master/...

[Detailed error messages with GitHub URLs]
```

## Validation Results: Errors vs Warnings

The validation system distinguishes between **errors** (blocking issues) and **warnings** (informational):

| Result Type | Description | Impact |
|-------------|-------------|--------|
| **ERROR** | Mismatch between OCP release and managed-cluster-config (missing expected changes) | Validation FAILS (exit 1) |
| **WARNING** | Unexpected changes in managed-cluster-config (not in OCP release payload) | Validation PASSES but warns (exit 0) |

### Example Output

**ERROR (Validation Fails):**
```
MISMATCH: Expected actions added in OCP release but NOT found in managed-cluster-config:
  • ec2:DescribeVpcEndpoints
  • s3:CreateBucket
  Review policies at: https://github.com/openshift/managed-cluster-config/tree/master/resources/sts/4.22
```

**WARNING (Validation Passes with Information):**
```
UNEXPECTED: Actions added in managed-cluster-config (not in OCP release):
  • ec2:DescribeNetworkInterfaces
  Review policies at: https://github.com/openshift/managed-cluster-config/tree/master/resources/sts/4.22
  Files with unexpected changes:
    - sts_installer_permission_policy.json
      Introduced in PR #1234: https://github.com/openshift/managed-cluster-config/pull/1234
```

**PR Link Feature:** When unexpected changes are detected (warnings), the validation system automatically searches for the GitHub PR that introduced the change using the GitHub REST API (unauthenticated, 60 requests/hour). If a `GH_TOKEN` is available, it uses authenticated requests for higher rate limits and falls back to `gh` CLI if needed. This helps identify the context and reasoning behind managed-cluster-config changes that differ from the OCP payload.

## Validation Details

### Check 1: AWS STS Resources

**What it validates:**
- Target version directory exists: `resources/sts/{version}/`
- All policy files are valid JSON with required structure
- Policy changes match OCP release credential request changes using **per-file comparison**
- Per-file comparison aggregates all permission changes across individual CredentialRequest files (a permission can be new to one CR but already exist in another)
- No unexpected files added or removed
- Actions (permissions) in managed-cluster-config match OCP release per-file changes

**Files checked:**
- All JSON files dynamically discovered in `resources/sts/{version}/`
- Typically 30+ policy files

**Pass criteria:**
- All policy files exist and are valid JSON
- Policy changes match OCP release changes exactly (ERRORS cause failure)
- Unexpected permissions generate WARNINGS but do not fail validation

### Check 2: AWS STS Admin Ack

**What it validates:**
- `config.yaml` exists and is valid
- `config.yaml` has correct baseline version selector
- `osd-sts-ack_CloudCredential.yaml` exists and is valid
- CloudCredential has correct upgrade version annotation

**Files checked:**
- `deploy/osd-cluster-acks/sts/{version}/config.yaml`
- `deploy/osd-cluster-acks/sts/{version}/osd-sts-ack_CloudCredential.yaml`

**Pass criteria:**
- Both files exist and are valid YAML
- Baseline version matches expected (target - 1)
- Upgrade version matches target version

### Check 3: GCP WIF Resources

**What it validates:**
- Target version directory exists: `resources/wif/{version}/`
- `vanilla.yaml` exists and is valid
- WIF template has correct structure (id, kind, service_accounts)
- GCP permissions in template match OCP release changes using **per-file comparison**
- Per-file comparison aggregates all permission changes across individual CredentialRequest files (a permission can be new to one CR but already exist in another)

**Files checked:**
- `resources/wif/{version}/vanilla.yaml`

**Pass criteria:**
- vanilla.yaml exists and is valid YAML
- Template structure is correct
- GCP permissions match OCP release changes exactly (ERRORS cause failure)
- Unexpected permissions generate WARNINGS but do not fail validation

### Check 4: GCP WIF Admin Ack

**What it validates:**
- `config.yaml` exists and is valid
- `config.yaml` has correct baseline version selector
- `osd-wif-ack_CloudCredential.yaml` exists and is valid
- CloudCredential has correct upgrade version annotation

**Files checked:**
- `deploy/osd-cluster-acks/wif/{version}/config.yaml`
- `deploy/osd-cluster-acks/wif/{version}/osd-wif-ack_CloudCredential.yaml`

**Pass criteria:**
- Both files exist and are valid YAML
- Baseline version matches expected (target - 1)
- Upgrade version matches target version

### Check 5: OCP Admin Gates

**What it validates:**
- Admin gates from baseline version are acknowledged in target version
- Acknowledgment structure follows conditional presence rules
- All required gates are acknowledged when gates exist
- `config.yaml` and `admin-ack.yaml` are present together or absent together

**Conditional validation logic:**
- **If gates exist in baseline**: BOTH `config.yaml` AND `admin-ack.yaml` MUST be present in target, all gates must be acknowledged
- **If no gates in baseline**: BOTH files MUST be absent (directory should not exist)
- Files must always be present together or absent together

**Files checked:**
- Admin gates from: `github.com/openshift/cluster-version-operator/release-{version}/...`
- Acknowledgments from: `deploy/osd-cluster-acks/ocp/{version}/admin-ack.yaml`
- Config from: `deploy/osd-cluster-acks/ocp/{version}/config.yaml`

**Pass criteria:**
- **No gates scenario**: Both `config.yaml` and `admin-ack.yaml` are absent
- **Gates exist scenario**: Both files present, all gates acknowledged, config.yaml has correct baseline version

### Check 6: Feature Gates

**What it analyzes:**
- New feature gates added
- Feature gates removed
- Feature gates newly enabled by default
- Feature gates removed from default

**Data source:**
- Sippy API: `https://sippy.dptools.openshift.org/api/feature_gates?release={version}`

**Pass criteria:**
- Always PASS (informational only)
- Analysis completes successfully
- Changes are tracked but do not affect exit code

## Exit Codes

### Individual Scripts (gap-aws-sts.py, gap-gcp-wif.py, gap-ocp-gate-ack.py)
- **Exit 0 (PASS):** All relevant checks passed
- **Exit 1 (FAIL):** One or more checks failed OR execution error

### Feature Gates Script (gap-feature-gates.py)
- **Exit 0 (PASS):** Always (informational only)
- **Exit 1 (FAIL):** Only on execution error (network, invalid version, etc.)

### Combined Script (gap-all.sh)
- **Exit 0 (PASS):** All checks 1-5 passed (check 6 is informational)
- **Exit 1 (FAIL):** Any of checks 1-5 failed OR execution error

## CI/CD Integration

The check numbering is consistent across:
- Console output
- Report files (HTML, JSON)
- Exit codes
- Log messages

This allows CI/CD systems to reliably:
- Parse specific check results from logs
- Identify which validation failed
- Link directly to [managed-cluster-config](https://github.com/openshift/managed-cluster-config) files needing updates
