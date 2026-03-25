# OpenShift Gap Analysis Framework

Automated tools and AI-assisted analysis for comparing cloud credential policies and feature gates across OpenShift versions.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Overview

This framework helps platform teams identify IAM permission and feature gate changes between OpenShift versions, ensuring proper cloud permissions are in place before upgrades.

### What It Analyzes

| Analysis Type | Description | Platforms |
|---------------|-------------|-----------|
| **AWS STS Policies** | IAM permission changes for AWS-based clusters | OSD AWS, ROSA Classic, ROSA HCP |
| **GCP WIF Policies** | Workload Identity Federation changes for GCP clusters | OSD GCP |
| **Feature Gates** | Feature gate additions, removals, and default enablement changes | All platforms |

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
- [🚀 Getting Started](docs/getting-started.md) - Installation and basic usage
- [⚙️ Configuration](docs/configuration.md) - CLI arguments, environment variables, version resolution
- [🔄 CI/CD Integration](docs/ci-integration.md) - Pipeline integration patterns
- [🔧 Development](docs/development.md) - Contributing and customization

**Additional Resources:**
- [📊 Report Documentation](REPORTS.md) - Report formats and viewing
- [🐳 Container Image](ci/README.md) - CI container image details

## Repository Structure

```
gap-analysis/
├── scripts/                  # Executable scripts
│   ├── gap-aws-sts.py       # AWS STS policy analysis
│   ├── gap-gcp-wif.py       # GCP WIF policy analysis
│   ├── gap-feature-gates.py # Feature gate analysis
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
[SUCCESS] Combined report generated: ./reports/gap-analysis-full_*.md
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
