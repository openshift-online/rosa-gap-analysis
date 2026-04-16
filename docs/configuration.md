# Configuration

Configuration options for gap analysis scripts.

## Command-Line Arguments

All Python scripts support:

```bash
--baseline <version>     # Baseline version (default: auto-detect)
--target <version>       # Target version (default: auto-detect)
--report-dir <path>      # Report directory (default: reports/)
--verbose                # Enable verbose logging
-h, --help               # Show help
```

**gap-all.sh** orchestrator supports the same arguments.

## Environment Variables

```bash
BASE_VERSION=<version>   # Override baseline
TARGET_VERSION=<version> # Override target (supports NIGHTLY, CANDIDATE)
REPORT_DIR=<path>        # Report directory
```

## Precedence

Versions are resolved in this order:
1. Command-line flags
2. Environment variables
3. Auto-detection (latest stable → latest candidate)

## Version Formats

### Supported Formats

```bash
# Minor version
--baseline 4.21 --target 4.22

# Full version
--baseline 4.21.7 --target 4.22.0-ec.4

# Pullspec
--baseline quay.io/openshift-release-dev/ocp-release:4.21.7-x86_64
```

### Special Keywords

```bash
TARGET_VERSION=NIGHTLY    # Latest dev nightly build
TARGET_VERSION=CANDIDATE  # Latest dev candidate (default)
```

## Auto-Detection

When versions are not specified:

- **Baseline**: Latest stable release for GA version
  - Queries: GA version (4.21) → Stable release (4.21.7)

- **Target**: Latest candidate release for dev version
  - Queries: Dev version (4.22 = GA+1) → Candidate (4.22.0-ec.4)

### Feature Gates Special Case

Feature gates API requires minor versions (4.21, 4.22).

Full versions are automatically converted:
- `4.21.7` → `4.21`
- `4.22.0-ec.4` → `4.22`

## Report Configuration

### Default Location

```bash
./reports/  # Current directory
```

### Custom Location

```bash
# Via flag
python3 ./scripts/gap-aws-sts.py --report-dir /custom/reports

# Via environment variable
REPORT_DIR=/tmp/reports ./scripts/gap-all.sh

# For CI artifacts
REPORT_DIR=${ARTIFACT_DIR}/gap-reports ./scripts/gap-all.sh
```

### Report Naming

```
gap-analysis-<type>_<baseline>_to_<target>_<timestamp>.<ext>

Examples:
  gap-analysis-aws-sts_4.21.7_to_4.22.0-ec.4_20260325_154133.html
  gap-analysis-aws-sts_4.21.7_to_4.22.0-ec.4_20260325_154133.json
  gap-analysis-feature-gates_4.21_to_4.22_20260325_154148.html
  gap-analysis-feature-gates_4.21_to_4.22_20260325_154148.json
  gap-analysis-full_4.21.7_to_4.22.0-ec.4_20260325_154148.html
  gap-analysis-full_4.21.7_to_4.22.0-ec.4_20260325_154148.json
```

## Examples

### Basic Usage

```bash
# Auto-detect everything
./scripts/gap-all.sh

# Explicit versions
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# With custom report location
./scripts/gap-all.sh --baseline 4.21 --target 4.22 --report-dir /tmp/reports
```

### Environment Variables

```bash
# Override baseline only
BASE_VERSION=4.21.5 ./scripts/gap-all.sh

# Override both
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 ./scripts/gap-all.sh

# Use nightly
TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh
```

### Mixed Configuration

```bash
# Flag takes precedence over environment
BASE_VERSION=4.21.0 ./scripts/gap-all.sh --baseline 4.21.7
# Result: Uses 4.21.7 (from flag)
```

## Sippy API

Scripts query these endpoints for auto-detection:

```
https://sippy.dptools.openshift.org/api/releases
https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/{version}/latest
https://sippy.dptools.openshift.org/api/feature_gates?release={version}
```

## Troubleshooting

**Network errors:**
```bash
# Specify versions explicitly
./scripts/gap-all.sh --baseline 4.21.7 --target 4.22.0-ec.4
```

**Version doesn't exist:**
```bash
# Verify version
oc adm release info quay.io/openshift-release-dev/ocp-release:4.99-x86_64
```

**Report directory issues:**
```bash
# Ensure writable
mkdir -p reports
chmod 755 reports
```
