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
- Claude Code (optional) - for using AI skills

### Local Usage

#### Run a single gap analysis

```bash
# Analyze AWS STS policy gaps between versions
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22
# Exit code 0: No differences, Exit code 1: Differences found

# Analyze GCP WIF policy gaps
./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22
# Exit code 0: No differences, Exit code 1: Differences found
```

#### Run gap analysis with gap-all.sh

```bash
# Run analysis for both AWS STS and GCP WIF
./scripts/gap-all.sh --baseline 4.21 --target 4.22
# Automatically runs both AWS and GCP analyses
```

#### Use in CI/CD pipelines

```bash
# Block on policy changes (any platform)
if ! ./scripts/gap-all.sh --baseline 4.21 --target 4.22; then
  echo "Policy changes detected - review required"
  exit 1
fi

# Allow policy changes but notify
if ./scripts/gap-all.sh --baseline 4.21 --target 4.22; then
  echo "No policy changes detected in any platform"
else
  echo "Policy changes detected in at least one platform" | notify-slack
fi

# Individual platform checks
if ! ./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22; then
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
│   │   └── common.sh         # Utilities (logging, colors, etc.)
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

## Script Arguments

Individual gap analysis scripts:

```bash
--baseline <version>    # Baseline version (e.g., 4.21)
--target <version>      # Target version to compare (e.g., 4.22)
--verbose               # Enable verbose logging (optional)
```

Gap-all orchestrator script:

```bash
--baseline <version>    # Baseline version (e.g., 4.21)
--target <version>      # Target version to compare (e.g., 4.22)
--verbose               # Enable verbose logging (optional)
```

**Note:** The gap-all.sh script runs analysis for both AWS and GCP platforms automatically.

**Exit Codes:**
- `0`: No policy differences found in any platform
- `1`: Policy differences detected in at least one platform

## Comparison Scenarios

### Version Upgrade Analysis (All Platforms)
```bash
# Run analysis for both AWS STS and GCP WIF: 4.21 → 4.22
./scripts/gap-all.sh --baseline 4.21 --target 4.22
echo $?  # 0 = no changes in any platform, 1 = changes detected in at least one
```

### Individual Script Usage
```bash
# AWS STS analysis
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22

# GCP WIF analysis
./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22

# With verbose logging
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22 --verbose
```

## Output Format

Scripts output log messages to stderr and exit with appropriate codes:

**No differences found:**
```
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Fetching baseline STS policy...
[SUCCESS] Successfully extracted STS policy
[INFO] Fetching target STS policy...
[SUCCESS] Successfully extracted STS policy
[INFO] Comparing STS policies...
[SUCCESS] No policy differences found between 4.21 and 4.22
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
