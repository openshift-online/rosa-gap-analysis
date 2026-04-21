# OpenShift Gap Analysis Framework

Automated tools and AI-assisted analysis for comparing cloud credential policies and feature gates across OpenShift versions.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Overview

This framework helps platform teams identify IAM permission and feature gate changes between OpenShift versions, ensuring proper cloud permissions are in place before upgrades.

### What It Analyzes

The framework performs **6 validation checks** across all scripts:

| Check # | Analysis Type | Description | Pass/Fail Impact |
|---------|---------------|-------------|------------------|
| **1** | AWS STS Resources | Validates STS policy files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) | Exit 1 on FAIL |
| **2** | AWS STS Admin Ack | Validates AWS acknowledgment files | Exit 1 on FAIL |
| **3** | GCP WIF Resources | Validates WIF template in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) | Exit 1 on FAIL |
| **4** | GCP WIF Admin Ack | Validates GCP acknowledgment files | Exit 1 on FAIL |
| **5** | OCP Admin Gates | Validates admin gate acknowledgments | Exit 1 on FAIL |
| **6** | Feature Gates | Tracks feature gate changes (informational) | Always PASS |

See [Validation Checks](docs/validation-checks.md) for detailed information about each check.

### Key Features

- 🚀 **Automated Analysis**: Scripts handle data extraction and comparison
- 📊 **Multi-Format Reports**: Generate HTML and JSON reports automatically
- 🔄 **Auto-Detection**: Automatically detect latest stable and candidate versions
- 🤖 **AI-Powered**: Claude Code skills for intelligent analysis and recommendations
- ✅ **CI/CD Ready**: Exit codes designed for pipeline integration
- 📦 **Container-Based**: Pre-built container image for OpenShift CI (Prow)

## Quick Start

### Installation

```bash
# Install prerequisites
pip install pyyaml

# Download OpenShift CLI
curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz | tar xz
```

See [Installation Guide](docs/getting-started.md) for detailed setup instructions.

### Run Gap Analysis

```bash
# Auto-detect versions (compares latest stable → latest candidate)
./scripts/gap-all.sh

# Specify versions explicitly
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# Test against nightly builds
TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh

# Custom report directory
REPORT_DIR=/custom/reports ./scripts/gap-all.sh
```

### View Reports

Reports are automatically generated in `./reports/` directory:

```bash
# Open HTML report in browser
firefox reports/gap-analysis-full_*.html

# Parse JSON report programmatically
jq '.aws_sts.comparison' reports/gap-analysis-full_*.json
```

## Quick Reference

### Version Queries (Accepted Builds)

Quick curl commands to check current OpenShift versions from accepted release streams:

```bash
# Get latest GA version from Sippy
curl -s https://sippy.dptools.openshift.org/api/releases | \
  jq -r '.ga_dates | keys | sort_by(split(".") | map(tonumber)) | last'

# Get latest stable for GA line (e.g., 4.21.x)
curl -s https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted | \
  jq -r '.["4-stable"][] | select(startswith("4.21."))' | head -1

# Get latest RC candidate (e.g., 4.22.0-rc.*)
curl -s https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted | \
  jq -r '.["4-stable"][] | select(startswith("4.22.0-rc."))' | head -1

# Get latest EC candidate (e.g., 4.22.0-ec.*)
curl -s https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted | \
  jq -r '.["4-dev-preview"][] | select(startswith("4.22.0-ec."))' | head -1

# All accepted 4-stable versions
curl -s https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted | \
  jq -r '.["4-stable"][]'
```

**Note:** These queries return only **accepted** builds that have passed CI testing. The framework uses this endpoint to ensure reliable version selection.

## Documentation

- [📘 Overview](docs/overview.md) - What gap analysis does and how it works
- [✅ Validation Checks](docs/validation-checks.md) - Details about all 6 validation checks
- [🚀 Getting Started](docs/getting-started.md) - Installation and basic usage
- [⚙️ Configuration](docs/configuration.md) - CLI arguments, environment variables, version resolution
- [🔧 Development](docs/development.md) - Contributing and customization

**Additional Resources:**
- [📊 Report Documentation](docs/reports.md) - Report formats and viewing
- [🐳 Container Image](ci/README.md) - CI container image details

## Repository Structure

```
gap-analysis/
├── scripts/                  # Executable scripts
│   ├── gap-aws-sts.py       # AWS STS policy analysis
│   ├── gap-gcp-wif.py       # GCP WIF policy analysis
│   ├── gap-feature-gates.py # Feature gate analysis
│   ├── gap-ocp-gate-ack.py  # OCP admin gate acknowledgment analysis
│   ├── gap-all.sh           # Run all analyses
│   └── lib/                 # Shared libraries
│
├── reports/                  # Generated reports (default location)
├── skills/                   # Claude AI skills
├── docs/                     # Documentation
└── ci/                       # CI configuration and container image
```

## Use Cases

### Pre-Upgrade Assessment
Understand IAM permission and feature gate changes before committing to a version upgrade.

### Security Review
Identify new cloud permissions and assess their security implications.

### Compliance Tracking
Track cloud permission evolution across OpenShift versions for security compliance.

### CI/CD Pipelines
Automatically detect policy changes in continuous integration workflows.

## Exit Code Behavior

Scripts are designed for CI/CD integration:

| Script | Exit 0 | Exit 1 |
|--------|--------|--------|
| `gap-aws-sts.py` | Successful execution | Execution error OR validation FAIL (checks 1-2) |
| `gap-gcp-wif.py` | Successful execution | Execution error OR validation FAIL (checks 3-4) |
| `gap-ocp-gate-ack.py` | Successful execution | Execution error OR validation FAIL (check 5) |
| `gap-feature-gates.py` | Always on success | Execution error only (check 6 is informational) |
| `gap-all.sh` | All checks 1-5 pass | Any check 1-5 fails |

```bash
# Run full analysis; exits 1 if any validation checks fail
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# Parse JSON reports for programmatic analysis
jq -e '.comparison.actions.target_only | length > 0' reports/gap-analysis-aws-sts_*.json
```

See [Getting Started](docs/getting-started.md) for detailed examples.

## Claude Code Integration

With [Claude Code](https://claude.ai/code) installed, simply ask:

```
"Compare AWS STS policies between OpenShift 4.21 and 4.22"
"Analyze feature gate changes between versions"
"Run a full gap analysis for 4.21 to 4.22"
```

Claude will execute the scripts and provide intelligent analysis and recommendations.

## Comparison with osdctl

Gap analysis scripts use the same underlying approach as `osdctl iampermissions diff`:

```bash
# Both use: oc adm release extract --credentials-requests
osdctl iampermissions diff -c aws -b 4.21 -t 4.22

# Gap analysis adds:
# - Automatic report generation (HTML, JSON)
# - Feature gate analysis
# - Combined cross-platform analysis
# - CI/CD-friendly exit codes
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
```

## Contributing

We welcome contributions! See [Development Guide](docs/development.md) for:

- Setting up development environment
- Testing scripts locally
- Code style guidelines
- Contribution workflow

## Support

For issues or questions:
- Get in touch with ROSA SRE team
- Review [documentation](docs/)

## License

Apache License 2.0
