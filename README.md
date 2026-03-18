# OpenShift Gap Analysis Framework

A comprehensive framework for analyzing gaps between different versions and platforms of managed OpenShift offerings (OSD, ROSA Classic, ROSA HCP).

## Overview

This repository provides both automated scripts (for CI/Prow) and Claude AI skills for identifying and analyzing cloud credential policy gaps across OpenShift versions:

- **AWS STS Policies**: IAM permission changes for AWS-based clusters (OSD AWS, ROSA Classic, ROSA HCP)
- **GCP WIF Policies**: Workload Identity Federation permission changes for GCP-based clusters (OSD GCP)

**Exit Codes**: Scripts exit with code 0 if no policy differences found, code 1 if differences detected - designed for CI/CD integration.

## Quick Start

### Prerequisites

- `oc` CLI (OpenShift client) - **required** for extracting credential requests from releases
- `jq` - **required** for JSON processing
- `yq` or `python3` with PyYAML - **required** for YAML parsing
- `curl` - **required** for fetching release information
- Claude Code (optional) - for using AI skills

### Local Usage

#### Auto-detect versions (recommended)

```bash
# Run analysis with auto-detected versions
# Baseline: latest stable version (e.g., 4.21.6)
# Target: latest candidate version (e.g., 4.22.0-ec.3)
./scripts/gap-all.sh
# Exit code 0: No differences, Exit code 1: Differences found

# Auto-detect with nightly target
TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh

# Individual platform analysis with auto-detection
./scripts/gap-aws-sts.sh
./scripts/gap-gcp-wif.sh
```

#### Specify versions explicitly

```bash
# Analyze AWS STS policy gaps between specific versions
./scripts/gap-aws-sts.sh --baseline 4.21.6 --target 4.22.0-ec.3

# Analyze GCP WIF policy gaps
./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22

# Run analysis for both AWS STS and GCP WIF
./scripts/gap-all.sh --baseline 4.21 --target 4.22
```

#### Use environment variables

```bash
# Override versions using environment variables
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 ./scripts/gap-all.sh

# Use nightly build as target
TARGET_VERSION=NIGHTLY ./scripts/gap-aws-sts.sh

# Explicit candidate (same as default)
TARGET_VERSION=CANDIDATE ./scripts/gap-gcp-wif.sh
```

#### Use in CI/CD pipelines

```bash
# Block on policy changes (auto-detect versions)
if ! ./scripts/gap-all.sh; then
  echo "Policy changes detected - review required"
  exit 1
fi

# Test against nightly builds
if ! TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh; then
  echo "Policy changes detected in nightly - review required"
  exit 1
fi

# Explicit version checks
if ! ./scripts/gap-all.sh --baseline 4.21 --target 4.22; then
  echo "Policy changes detected - review required"
  exit 1
fi

# Allow policy changes but notify
if ./scripts/gap-all.sh; then
  echo "No policy changes detected in any platform"
else
  echo "Policy changes detected in at least one platform" | notify-slack
fi

# Individual platform checks with auto-detection
if ! ./scripts/gap-aws-sts.sh; then
  echo "AWS policy changes detected - review required"
  exit 1
fi
```

### Using Claude Skills

With Claude Code installed, simply ask:

```
"Compare AWS STS policies between OpenShift 4.21 and 4.22"

"Analyze GCP WIF policy changes between 4.21 and 4.22"

"Run a full gap analysis between 4.21 and 4.22"
```

The skills will leverage the scripts while providing intelligent analysis and recommendations. The full gap analysis skill automatically checks both AWS and GCP platforms.

## Repository Structure

```
gap-analysis/
├── scripts/                    # Executable bash scripts
│   ├── lib/                   # Shared libraries
│   │   ├── common.sh         # Utilities (logging, colors, etc.)
│   │   └── openshift-releases.sh  # OpenShift version/release queries
│   ├── gap-aws-sts.sh        # AWS STS policy gap analysis
│   ├── gap-gcp-wif.sh        # GCP WIF policy gap analysis
│   └── gap-all.sh            # Run all analyses
│
├── skills/                    # Claude AI skills
│   ├── aws-sts-gap/          # AWS STS gap analysis skill
│   ├── gcp-wif-gap/          # GCP WIF gap analysis skill
│   └── full-gap-analysis/    # Full gap analysis orchestration
│
├── .prow/                     # Prow CI configuration
├── docs/                      # Documentation
├── results/                   # Generated reports (gitignored)
└── examples/                  # Example outputs
```

## Gap Analysis Types

### 1. AWS STS Policies (`gap-aws-sts.sh`)

Compares AWS Security Token Service (STS) policies between versions to identify:
- New IAM permissions required
- Removed permissions
- Changed permission scopes

**Uses the same approach as `osdctl iampermissions diff`** - extracts CredentialsRequests from release payloads using `oc adm release extract`.

**Example:**
```bash
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22
# Exit code 0: No differences
# Exit code 1: Differences found
```

### 2. GCP WIF Policies (`gap-gcp-wif.sh`)

Compares Google Cloud Workload Identity Federation policies to identify:
- New GCP IAM roles/permissions
- Removed permissions
- Service account changes

**Uses the same approach as AWS STS** - extracts CredentialsRequests from release payloads using `oc adm release extract --cloud=gcp`.

**Example:**
```bash
./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22
# Exit code 0: No differences
# Exit code 1: Differences found
```

### 3. OpenShift Release Information Library (`lib/openshift-releases.sh`)

A comprehensive library for querying OpenShift release data from Sippy API and OCP release streams.

**Key Features:**
- Auto-detect latest GA, dev, stable, and candidate versions
- Version validation (dev = GA + 1, candidate belongs to dev, stable belongs to GA)
- Fetch release image pullspecs
- Query nightly builds
- Both CLI and library (sourceable) interface

**CLI Usage:**
```bash
# Query versions
./scripts/lib/openshift-releases.sh --latest-ga              # 4.21
./scripts/lib/openshift-releases.sh --latest-dev             # 4.22 (GA+1)
./scripts/lib/openshift-releases.sh --latest-stable          # 4.21.6
./scripts/lib/openshift-releases.sh --latest-candidate       # 4.22.0-ec.3
./scripts/lib/openshift-releases.sh --latest-nightly         # 4.22.0-0.nightly-...

# Get pullspecs
./scripts/lib/openshift-releases.sh --latest-stable-pullspec
# quay.io/openshift-release-dev/ocp-release:4.21.6-x86_64

./scripts/lib/openshift-releases.sh --latest-candidate-pullspec
# quay.io/openshift-release-dev/ocp-release:4.22.0-ec.3-x86_64

./scripts/lib/openshift-releases.sh --latest-nightly-pullspec
# registry.ci.openshift.org/ocp/release:4.22.0-0.nightly-...

# Nightly for specific version
./scripts/lib/openshift-releases.sh --nightly 4.22
```

**Library Usage (in scripts):**
```bash
source scripts/lib/openshift-releases.sh

# Get versions
ga_version=$(get_latest_ga_version)              # 4.21
dev_version=$(get_latest_dev_version)            # 4.22
stable=$(get_latest_stable_version)              # 4.21.6
candidate=$(get_latest_candidate_version)        # 4.22.0-ec.3
nightly=$(get_latest_dev_nightly_version)        # 4.22.0-0.nightly-...

# Get pullspecs
stable_pullspec=$(get_latest_stable_pullspec)
candidate_pullspec=$(get_latest_candidate_pullspec)
nightly_pullspec=$(get_latest_dev_nightly_pullspec)

# Validation functions
validate_version_gap "4.21" "4.22"               # Returns 0 if valid
validate_candidate_belongs_to_version "4.22.0-ec.3" "4.22"
validate_stable_belongs_to_version "4.21.6" "4.21"
```

**Validation Rules:**
- Dev version must be exactly GA + 1 (e.g., GA=4.21, dev=4.22)
- Candidate versions must belong to dev version (e.g., 4.22.0-ec.3 → 4.22)
- Stable versions must belong to GA version (e.g., 4.21.6 → 4.21)
- All validation is automatic when using the library functions

## Script Arguments

### Command-line Flags

All scripts support these optional flags:

```bash
--baseline <version>    # Baseline version (default: auto-detect from latest stable)
                        # Examples: 4.21, 4.21.6, full pullspec
--target <version>      # Target version (default: auto-detect from latest candidate)
                        # Examples: 4.22, 4.22.0-ec.3, full pullspec
--verbose               # Enable verbose logging
-h, --help              # Show help message
```

### Environment Variables

Override versions using environment variables (lower precedence than CLI flags):

```bash
BASE_VERSION           # Override baseline version
                       # Examples: 4.21.5, 4.21, full pullspec

TARGET_VERSION         # Override target version
                       # Examples: 4.22.0-ec.2, NIGHTLY, CANDIDATE
                       # Special values:
                       #   NIGHTLY - latest dev nightly build
                       #   CANDIDATE - latest dev candidate (default)
```

### Version Resolution Precedence

Versions are resolved in this order (highest to lowest):
1. **Command-line flags** (`--baseline`, `--target`)
2. **Environment variables** (`BASE_VERSION`, `TARGET_VERSION`)
3. **Auto-detected** (latest stable for baseline, latest candidate for target)

### Auto-Detection Details

When versions are auto-detected:
- **Baseline**: Latest stable release for GA version (e.g., `4.21.6` for GA `4.21`)
- **Target**: Latest candidate release for dev version (e.g., `4.22.0-ec.3` for dev `4.22`)
- **Dev version**: Always exactly GA + 1 (e.g., GA=`4.21`, dev=`4.22`)
- **Pullspecs**: Automatically fetched and used when auto-detecting

**Note:** The gap-all.sh script runs analysis for both AWS and GCP platforms automatically.

**Exit Codes:**
- `0`: No policy differences found in any platform
- `1`: Policy differences detected in at least one platform

## Comparison Scenarios

### Auto-Detected Analysis (Recommended)
```bash
# Run analysis with auto-detected versions
# Compares latest stable → latest candidate
./scripts/gap-all.sh
echo $?  # 0 = no changes, 1 = changes detected

# Use latest nightly as target
TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh

# Individual platform with auto-detection
./scripts/gap-aws-sts.sh
./scripts/gap-gcp-wif.sh
```

### Explicit Version Analysis
```bash
# Run analysis for both AWS STS and GCP WIF: 4.21 → 4.22
./scripts/gap-all.sh --baseline 4.21 --target 4.22
echo $?  # 0 = no changes in any platform, 1 = changes detected

# AWS STS analysis
./scripts/gap-aws-sts.sh --baseline 4.21.6 --target 4.22.0-ec.3

# GCP WIF analysis
./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22

# With verbose logging
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22 --verbose
```

### Environment Variable Usage
```bash
# Override baseline, auto-detect target
BASE_VERSION=4.21.5 ./scripts/gap-all.sh

# Use specific versions
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 ./scripts/gap-all.sh

# Compare stable against nightly
TARGET_VERSION=NIGHTLY ./scripts/gap-aws-sts.sh
```

## Output Format

Scripts output log messages to stderr and exit with appropriate codes:

**Auto-detected versions (no differences found):**
```
[INFO] Auto-detecting baseline version from latest stable...
[INFO] Auto-detected baseline version: 4.21.6
[INFO] Auto-detected baseline pullspec: quay.io/openshift-release-dev/ocp-release:4.21.6-x86_64
[INFO] Auto-detecting target version from latest candidate...
[INFO] Auto-detected target version: 4.22.0-ec.3
[INFO] Auto-detected target pullspec: quay.io/openshift-release-dev/ocp-release:4.22.0-ec.3-x86_64
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] =========================================
[INFO] Baseline version: 4.21.6
[INFO] Baseline pullspec: quay.io/openshift-release-dev/ocp-release:4.21.6-x86_64
[INFO] Target version: 4.22.0-ec.3
[INFO] Target pullspec: quay.io/openshift-release-dev/ocp-release:4.22.0-ec.3-x86_64
[INFO] =========================================
[INFO] Fetching baseline STS policy...
[SUCCESS] Successfully extracted STS policy
[INFO] Fetching target STS policy...
[SUCCESS] Successfully extracted STS policy
[INFO] Comparing STS policies...
[SUCCESS] No policy differences found between 4.21.6 and 4.22.0-ec.3
```
Exit code: `0`

**Differences found:**
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

**For detailed analysis**, you can extract comparison data manually using the comparison functions in `scripts/lib/common.sh`.

## Examples

See the `examples/` directory for sample outputs:
- `examples/4.21-to-4.22-osd-aws/` - Version upgrade on AWS

## Development

### Testing Scripts Locally

```bash
# Enable verbose mode (see detailed logging)
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22 --verbose

# Test GCP WIF analysis
./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22 --verbose

# Check exit code
if ./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22; then
  echo "No differences found"
else
  echo "Differences found"
fi
```

### Comparing with osdctl

You can validate AWS STS results against osdctl:

```bash
# Using osdctl (simple diff)
osdctl iampermissions diff -c aws -b 4.21 -t 4.22

# Using gap-analysis (exit code based)
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22
echo "Exit code: $?"
```

Both use the same `oc adm release extract --credentials-requests --cloud=aws` under the hood.

### Extracting Detailed Comparison Data

If you need detailed comparison data for analysis:

```bash
# Source the functions
source scripts/lib/common.sh
source scripts/gap-aws-sts.sh

# Extract policies to temp files
baseline_policy=$(mktemp)
target_policy=$(mktemp)
get_sts_policy "4.21" > "$baseline_policy"
get_sts_policy "4.22" > "$target_policy"

# Compare and analyze
compare_sts_policies "$baseline_policy" "$target_policy" | jq '.actions'
```

## Support

For issues or questions:
- Get in touch with ROSA SRE team
