---
name: feature-gates-gap
description: >
  Analyze OpenShift feature gate differences between versions.
  Identifies new feature gates, removed gates, and default enablement changes.
  Logs detected feature gate changes but always exits 0 on successful execution.
  Automatically generates comprehensive reports in HTML and JSON formats.
compatibility:
  required_tools:
    - python3
    - curl (for Sippy API access)
---

# Feature Gate Gap Analysis

Analyze differences in OpenShift feature gates between versions using the Sippy API.

## When to Use

- Comparing feature gates between versions
- Planning cluster upgrades
- Understanding new capabilities in a release
- Tracking feature graduation (TechPreview → Default)
- CI/CD pipelines that need to detect feature changes

## Workflow

1. Parse baseline and target versions (default: auto-detect latest stable → latest candidate)
2. Fetch feature gate data from Sippy API for both versions
3. Compare **Hypershift-relevant** feature gates only (gates with `Default:Hypershift`, `DevPreviewNoUpgrade:Hypershift`, or `TechPreviewNoUpgrade:Hypershift` enablement) and identify:
   - New feature gates added in target version
   - Feature gates removed in target version
   - Feature gates newly enabled by default (`Default:Hypershift`) in target
   - Feature gates removed from default in target
   - Feature gates that continue as `Default:Hypershift` (already default, still default)
4. Log detected differences and always exit 0 on successful execution

## Script Usage

**Auto-detect versions (recommended):**
```bash
# Compares latest stable → latest candidate
python3 ./scripts/gap-feature-gates.py

# With verbose output
python3 ./scripts/gap-feature-gates.py --verbose

# Custom report directory
python3 ./scripts/gap-feature-gates.py --report-dir /custom/reports
```

**Explicit versions:**
```bash
python3 ./scripts/gap-feature-gates.py \
  --baseline <version> \
  --target <version> \
  [--report-dir <path>] \
  [--verbose]
```

**Examples:**
```bash
# Auto-detect
python3 ./scripts/gap-feature-gates.py

# Explicit versions
python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22

# With verbose output showing all changes
python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22 --verbose

# Environment variables
BASE_VERSION=4.21 TARGET_VERSION=4.22 python3 ./scripts/gap-feature-gates.py

# Use nightly as target
TARGET_VERSION=NIGHTLY python3 ./scripts/gap-feature-gates.py

# Custom report location
REPORT_DIR=/ci-artifacts python3 ./scripts/gap-feature-gates.py
```

**Generated Reports:**
```bash
reports/gap-analysis-feature-gates_4.21_to_4.22_20260325_120000.html  # HTML
reports/gap-analysis-feature-gates_4.21_to_4.22_20260325_120000.json  # JSON
```

**Exit Codes:**
- `0`: Successful execution (regardless of whether differences were found)
- `1`: Execution failure (e.g., missing tools, network errors, invalid versions)

**Version Resolution:**
- CLI flags > Environment variables > Auto-detect
- Auto-detect: latest stable (baseline) → latest candidate (target)
- Special keywords: `TARGET_VERSION=NIGHTLY` or `TARGET_VERSION=CANDIDATE`

## Key Focus Areas

Note: Only Hypershift-relevant gates are analyzed (gates with `Default:Hypershift`, `DevPreviewNoUpgrade:Hypershift`, or `TechPreviewNoUpgrade:Hypershift` enablement).

- **New Feature Gates**: Hypershift-relevant gates added in the target version
- **Removed Feature Gates**: Hypershift-relevant gates dropped from the target version
- **Default Enablement**: Gates newly enabled by default (`Default:Hypershift`) - important for upgrade planning
- **Removed from Default**: Gates that had `Default:Hypershift` in baseline but no longer do
- **Continues as Default**: Gates that continue as `Default:Hypershift` from baseline to target

## Output

The script outputs log messages and always exits 0 on successful execution:

**No differences:**
```
[INFO] Starting Feature Gate Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Fetching feature gates for version 4.21...
[SUCCESS] Fetched 125 feature gates for version 4.21
[INFO] Fetching feature gates for version 4.22...
[SUCCESS] Fetched 125 feature gates for version 4.22
[INFO] Comparing feature gates...
[SUCCESS] No feature gate differences found between 4.21 and 4.22
```

Exit code: `0` (successful execution, no differences)

**Differences found:**
```
[INFO] Starting Feature Gate Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Fetching feature gates for version 4.21...
[SUCCESS] Fetched 125 feature gates for version 4.21
[INFO] Fetching feature gates for version 4.22...
[SUCCESS] Fetched 130 feature gates for version 4.22
[INFO] Comparing feature gates...
[INFO] Feature gate differences detected (Hypershift-relevant only):
[INFO]   - New feature gates: 8
[INFO]   - Removed feature gates: 3
[INFO]   - Newly enabled by default (Default:Hypershift): 2
[INFO]   - Continues as Default:Hypershift: 5
```

Exit code: `0` (successful execution, differences found)

**With `--verbose`:**
```
[INFO] Feature gate differences detected:
[INFO]   - New feature gates: 8
[INFO]   - Newly enabled by default: 2

[INFO] New feature gates in 4.22:
[INFO]   + NewFeatureGate1
[INFO]   + NewFeatureGate2
[INFO]   + NewFeatureGate3
[INFO]   + NewFeatureGate4
[INFO]   + NewFeatureGate5
[INFO]   + NewFeatureGate6
[INFO]   + NewFeatureGate7
[INFO]   + NewFeatureGate8

[INFO] Newly enabled by default in 4.22:
[INFO]   ✓ PreviouslyTechPreviewGate
[INFO]   ✓ AnotherGraduatedGate
```

**Use in CI/CD:**
```bash
# Script always exits 0 on success
python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22

# Check for differences by parsing output
if python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22 2>&1 | grep -q "Feature gate differences detected"; then
  echo "Feature gate changes detected - review reports/"
else
  echo "No feature gate changes"
fi

# Use JSON report for programmatic analysis
python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22
if jq -e '.comparison.added | length > 0' reports/gap-analysis-feature-gates_*.json >/dev/null 2>&1; then
  echo "New feature gates detected"
fi
```

## Data Source

Uses Sippy API to fetch feature gate information:
- API endpoint: `https://sippy.dptools.openshift.org/api/feature_gates?release=<version>`
- Data includes:
  - Feature gate names
  - Enablement status (Default, DevPreviewNoUpgrade, TechPreviewNoUpgrade)
  - Platform variations (Hypershift, SelfManagedHA)
  - First seen version

## Going Beyond the Script

**Detailed Analysis:**
```bash
# Get raw feature gate data for manual analysis
curl -s "https://sippy.dptools.openshift.org/api/feature_gates?release=4.22" | jq '.'

# Filter for default-enabled gates only
curl -s "https://sippy.dptools.openshift.org/api/feature_gates?release=4.22" | \
  jq '.[] | select(.enabled[] | contains("Default:"))'

# Count gates by enablement level
curl -s "https://sippy.dptools.openshift.org/api/feature_gates?release=4.22" | \
  jq '[.[] | .enabled[] | split(":")[0]] | group_by(.) | map({key: .[0], count: length})'
```

**Understanding Feature Gate Lifecycle:**
- **TechPreviewNoUpgrade**: Early preview, no upgrade support
- **DevPreviewNoUpgrade**: Developer preview, no upgrade support
- **Default**: Enabled by default, production ready

**CI/CD Integration:**
- Parse script output to detect feature gate changes
- Script always exits 0 on successful execution regardless of differences
- Automate notifications when feature gates change
- Track feature graduation across releases

**Impact Analysis:**
- New default-enabled gates may affect cluster behavior
- Removed gates indicate deprecated features
- Gates graduating to default indicate feature stabilization
