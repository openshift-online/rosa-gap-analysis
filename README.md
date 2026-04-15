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
- 📊 **Multi-Format Reports**: Generate Markdown, HTML, and JSON reports automatically
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

See [Installation Guide](docs/installation.md) for detailed setup instructions.

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
# View Markdown report
cat reports/gap-analysis-full_*.md

# Open HTML report in browser
firefox reports/gap-analysis-full_*.html

# Parse JSON report programmatically
jq '.aws_sts.comparison' reports/gap-analysis-full_*.json
```

## Documentation

- [📘 Overview](docs/overview.md) - What gap analysis does and how it works
- [✅ Validation Checks](docs/validation-checks.md) - Details about all 6 validation checks
- [🚀 Getting Started](docs/getting-started.md) - Installation and basic usage
- [⚙️ Configuration](docs/configuration.md) - CLI arguments, environment variables, version resolution
- [🔄 CI/CD Integration](docs/ci-integration.md) - Pipeline integration patterns
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

## Examples

### AWS STS Policy Analysis

```bash
# Compare IAM permissions between versions
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22

# Output
[INFO] Starting AWS STS Policy Gap Analysis
[INFO] Baseline version: 4.21
[INFO] Target version: 4.22
[INFO] Policy differences detected: 3 added, 1 removed
[SUCCESS] Reports generated: ./reports/gap-analysis-aws-sts_*.{md,html,json}
```

### Feature Gates Analysis

```bash
# Compare feature gates between versions
python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22

# Output
[INFO] Feature gate differences detected:
[INFO]   - New feature gates: 8
[INFO]   - Newly enabled by default: 2
[SUCCESS] Reports generated: ./reports/gap-analysis-feature-gates_*.{md,html,json}
```

### Full Gap Analysis

```bash
# Run all analyses with combined report
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# Output
[INFO] OpenShift Gap Analysis Suite
[INFO] Running AWS STS Policy Gap Analysis...
[INFO] Running GCP WIF Policy Gap Analysis...
[INFO] Running Feature Gates Gap Analysis...
[INFO] Running OCP Admin Gate Acknowledgment Analysis...
[SUCCESS] Combined report generated: ./reports/gap-analysis-full_*.md
```

### Analyze CI Failures

When a Prow job fails, automatically analyze it and generate PR requirements:

```bash
# Analyze latest failed periodic job
./ci/prow/analyze-failure.sh

# Output
[INFO] Gap Analysis Failure Analyzer
[INFO] Finding latest failed job for: periodic-ci-openshift-online-rosa-gap-analysis-main-nightly
[SUCCESS] Found failed job: 2041035894848229376
[INFO] Downloading artifacts for job 2041035894848229376...
[SUCCESS] Downloaded: ci/artifacts/gap-analysis-full_4.21.9_to_4.22.0-ec.4_*.json
[INFO] Analyzing gap analysis report...
[SUCCESS] PR summary generated: ci/artifacts/pr-summary.md

# View PR summary
cat ci/artifacts/pr-summary.md
```

The analyzer automatically:
- Finds the latest **FAILED** Prow job
- Downloads gap-analysis artifacts locally to `ci/artifacts/`
- Parses validation failures from CHECK #1-5
- Extracts credentials from target OCP release (reuses gap-aws-sts.py/gap-gcp-wif.py functions)
- Generates exact file content for all missing files
- Creates `pr-summary.md` with copy-paste ready content for managed-cluster-config PR

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

- **Exit 0**: Successful execution (regardless of differences found)
- **Exit 1**: Execution failure (missing tools, network errors)

**Important**: Scripts do NOT fail when differences are detected. This prevents false CI failures when policies legitimately change between versions.

```bash
# Detect differences by parsing output
if ./scripts/gap-all.sh 2>&1 | grep -q "differences detected"; then
  echo "Policy changes detected - review reports/"
fi

# Or use JSON reports
jq -e '.comparison.actions.target_only | length > 0' reports/gap-analysis-aws-sts_*.json
```

See [CI/CD Integration](docs/ci-integration.md) for detailed examples.

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
# - Automatic report generation (MD, HTML, JSON)
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
