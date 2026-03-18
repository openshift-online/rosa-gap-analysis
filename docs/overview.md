# Gap Analysis Framework Overview

## Purpose

The OpenShift Gap Analysis Framework provides automated tooling and AI-assisted analysis for comparing cloud credential policies across OpenShift versions. It helps teams understand IAM permission changes required for version upgrades.

## What is Gap Analysis?

In the context of Managed OpenShift, Gap Analysis identifies cloud credential policy changes between OpenShift versions to ensure proper IAM permissions are in place before upgrades.

The goal is to identify IAM/WIF permission changes early, ensuring managed OpenShift clusters have the correct cloud permissions to run on new versions of OpenShift Container Platform.

## Supported Cloud Platforms

- **AWS** - AWS STS (Security Token Service) IAM policies
- **GCP** - GCP WIF (Workload Identity Federation) policies

## Analysis Categories

### AWS STS (Security Token Service) Policies

Analyzes IAM permission changes for AWS-based OpenShift clusters:
- IAM permissions required for cluster operations
- Service-specific permission scopes (EC2, ELB, S3, etc.)
- New or removed AWS service integrations
- Permission scope changes (Resource ARNs, wildcards)

**Extraction Method**: Uses `oc adm release extract --credentials-requests --cloud=aws` to extract CredentialsRequest manifests from OpenShift release payloads, then converts them to consolidated IAM policy JSON.

### GCP WIF (Workload Identity Federation) Policies

Analyzes GCP IAM permission changes for GCP-based OpenShift clusters:
- GCP IAM roles and bindings
- Service account configurations
- Workload Identity pool settings
- Permission changes across GCP services

**Extraction Method**: Uses `oc adm release extract --credentials-requests --cloud=gcp` to extract CredentialsRequest manifests from OpenShift release payloads, then converts them to GCP IAM policy format.

## Use Cases

### Pre-Upgrade IAM Assessment
Understand what IAM/WIF permission changes are required before committing to a version upgrade.

### Security Review
Identify new cloud permissions and assess their security implications.

### IAM Policy Updates
Generate the specific IAM policy changes needed for AWS or GCP before upgrading OpenShift clusters.

### Compliance and Auditing
Track cloud permission evolution across OpenShift versions for security compliance.

### Documentation Updates
Ensure IAM permission documentation and runbooks reflect version-specific requirements.

## Workflow

```
1. Identify baseline and target OpenShift versions
   (or use auto-detection for latest stable → latest candidate)
   ↓
2. Select cloud platform (AWS or GCP)
   ↓
3. Run gap analysis script
   ↓
4. Review credential policy changes in output
   ↓
5. Assess security implications
   ↓
6. Update IAM roles/policies in cloud provider
   ↓
7. Validate permissions before upgrade
   ↓
8. Execute OpenShift upgrade
```

## Tools Overview

### Automated Scripts
- **Pros**: Fast, consistent, CI-ready
- **Cons**: Limited to known patterns
- **Best for**: Regular checks, CI pipelines

### Claude Skills
- **Pros**: Intelligent analysis, context-aware, flexible
- **Cons**: Requires Claude Code
- **Best for**: Deep investigations, strategic planning

### Combined Approach
Use scripts for data collection and Claude for analysis and recommendations.

## Key Principles

1. **Automation First**: Scripts handle repetitive data collection
2. **Intelligence Layer**: AI provides analysis and insights
3. **Modularity**: Each gap type analyzed independently
4. **Reproducibility**: Same inputs → same outputs
5. **CI Integration**: Runs in Prow for continuous monitoring

## Getting Started

See the main [README.md](../README.md) for:
- Installation prerequisites
- Quick start examples
- Script usage instructions
- CI integration examples

## Example Commands

### AWS STS Analysis
```bash
# Auto-detect versions (latest stable → latest candidate)
./scripts/gap-aws-sts.sh

# Explicit versions
./scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22

# Use nightly as target
TARGET_VERSION=NIGHTLY ./scripts/gap-aws-sts.sh

# Environment variables
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 ./scripts/gap-aws-sts.sh
```

### GCP WIF Analysis
```bash
# Auto-detect versions
./scripts/gap-gcp-wif.sh

# Explicit versions
./scripts/gap-gcp-wif.sh --baseline 4.21 --target 4.22

# Use nightly as target
TARGET_VERSION=NIGHTLY ./scripts/gap-gcp-wif.sh
```

### Using gap-all.sh Orchestrator
```bash
# Auto-detect versions (recommended)
./scripts/gap-all.sh

# Explicit versions for both platforms
./scripts/gap-all.sh --baseline 4.21 --target 4.22

# Use nightly as target
TARGET_VERSION=NIGHTLY ./scripts/gap-all.sh

# Environment variables
BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 ./scripts/gap-all.sh
```

### Version Resolution

Versions are resolved in this order (highest to lowest priority):
1. Command-line flags (`--baseline`, `--target`)
2. Environment variables (`BASE_VERSION`, `TARGET_VERSION`)
3. Auto-detected (latest stable for baseline, latest candidate for target)

Special `TARGET_VERSION` values:
- `NIGHTLY` - Uses latest dev nightly build
- `CANDIDATE` - Uses latest dev candidate (default when auto-detecting)
