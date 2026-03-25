# Overview

OpenShift Gap Analysis Framework for comparing cloud credential policies and feature gates across OpenShift versions.

## What It Does

Identifies changes between OpenShift versions in three areas:

1. **AWS STS Policies** - IAM permission changes for AWS clusters (OSD AWS, ROSA Classic, ROSA HCP)
2. **GCP WIF Policies** - Workload Identity Federation changes for GCP clusters (OSD GCP)
3. **Feature Gates** - Feature additions, removals, and default enablement changes

## How It Works

```
1. Specify versions (or auto-detect latest stable → candidate)
   ↓
2. Extract credential requests / feature gates
   ↓
3. Compare and generate reports (MD, HTML, JSON)
   ↓
4. Review changes and assess impact
```

## Key Features

- **Automated extraction** - Uses `oc adm release extract` and Sippy API
- **Multi-format reports** - Markdown, HTML, and JSON
- **Auto-detection** - Automatically finds latest versions
- **CI/CD ready** - Exit codes designed for pipelines
- **Template-based** - Jinja2 templates for easy customization

## Use Cases

**Pre-Upgrade Assessment**
```bash
./scripts/gap-all.sh --baseline 4.21 --target 4.22
```

**Security Review**
```bash
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
jq '.comparison.actions.target_only' reports/*.json
```

**CI/CD Integration**
```bash
if ./scripts/gap-all.sh 2>&1 | grep -q "differences detected"; then
  echo "Review reports/"
fi
```

## Tools

**Scripts** (Python + Bash)
- Fast, consistent, CI-ready
- Automatic report generation
- Best for: Regular checks, automation

**Claude Skills** (AI-powered)
- Intelligent analysis, recommendations
- Context-aware suggestions
- Best for: Deep investigations, planning

## Data Sources

**AWS STS / GCP WIF:**
- `oc adm release extract --credentials-requests --cloud={aws,gcp}`
- Extracts CredentialsRequest manifests from release images
- Same approach as `osdctl iampermissions diff`

**Feature Gates:**
- `https://sippy.dptools.openshift.org/api/feature_gates?release={version}`
- Queries Sippy API for feature gate data

## Reports

**Formats:**
- Markdown - Terminal viewing, version control
- HTML - Browser viewing, presentations
- JSON - Programmatic analysis, CI/CD

**Location:**
- Default: `./reports/`
- Configurable via `--report-dir` or `REPORT_DIR`

**Naming:**
```
gap-analysis-<type>_<baseline>_to_<target>_<timestamp>.<ext>
```

## Quick Links

- [Getting Started](getting-started.md) - Installation and basic usage
- [Configuration](configuration.md) - CLI args, env vars, version resolution
- [CI/CD Integration](ci-integration.md) - Pipeline integration
- [Development](development.md) - Contributing and customization
