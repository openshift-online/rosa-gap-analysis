# Overview

OpenShift Gap Analysis Framework for comparing cloud credential policies and feature gates across OpenShift versions.

## What It Does

Identifies changes between OpenShift versions through 13 validation checks:

**Checks 1-2: AWS STS Validation**
- **Check 1:** AWS STS Resources - Validates policy files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- **Check 2:** AWS STS Admin Ack - Validates acknowledgment files for AWS clusters

**Checks 3-4: GCP WIF Validation**
- **Check 3:** GCP WIF Resources - Validates WIF template in [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- **Check 4:** GCP WIF Admin Ack - Validates acknowledgment files for GCP clusters

**Check 5: OCP Admin Gate Acknowledgments**
- **Check 5:** OCP Admin Gates - Validates upgrade readiness by checking required gate acknowledgments

**Check 6: Versions & Channels**
- **Check 6:** Versions & Channels - Validates version availability across OCM release channels and marketplace enablement (ROSA Classic, ROSA HCP, OSD GCP)

**Check 7: OCM Version Gates**
- **Check 7:** OCM Version Gates - Validates OCM version gate existence, configurations, and metadata

**Check 8: Feature Gates (Informational)**
- **Check 8:** Feature Gates - Tracks feature additions, removals, and default enablement changes (informational only, always PASS)

**Check 9: API Resources and CRD Diff Validation (Informational)**
- **Check 9:** API Resources and CRD Diff Validation - Compares live ROSA API resources and CRDs (HCP, Classic, and OSD GCP; OSD GCP skipped for 5.x; informational; SKIP if snapshots are missing)

**Check 10: Critical Alerts Diff Validation (Informational)**
- **Check 10:** Critical Alerts Diff Validation - Compares live PrometheusRule alerts and recommends inherit / silence / review (informational; SKIP if snapshots are missing)

**Check 11: Cluster Install and Delete Validation (Informational)**
- **Check 11:** Cluster Install and Delete Validation - Compares live ClusterOperator/node install health from rosa-e2e post-phase snapshots (HCP, Classic, and OSD GCP; OSD GCP skipped for 5.x; informational; SKIP if snapshots are missing). Delete-duration metrics are not in the snapshot yet.

**Check 12: Target E2E Validation and alert monitoring (Informational)**
- **Check 12:** Target E2E Validation and alert monitoring - Consumes target-version rosa-e2e JUnit from HCP, Classic, and OSD GCP. Failed tests are reported as FAIL in the report and do not fail the job. Missing JUnit is SKIP. OSD GCP is skipped for OpenShift 5.x. Alert monitoring is SKIP until VerifyNoCriticalAlerts exists in rosa-e2e.

**Check 13: Upgrade Validation from Y-1 to Y with E2E Tests**
- **Check 13:** Upgrade Validation from Y-1 to Y with E2E Tests - Consumes rosa-e2e HCP, Classic, and OSD GCP Y-1 upgrade periodics. Failed post-upgrade e2e or unhealthy ClusterOperators FAIL. Duration comes from upgrade-metrics.json or finished.json. Missing JUnit is SKIP.

## How It Works

```
1. Specify versions (or auto-detect latest stable → candidate)
   ↓
2. gap-all.sh runs 13 checks, delegating each to its step-registry commands.sh (policy, channels, Prow artifacts, E2E JUnit)
   ↓
3. Each script writes JSON + status-check-<n>.json
   ↓
4. generate-combined-report.py → gap-analysis-full_*.{html,json}
   ↓
5. Review combined report; job exits 1 if checks 1–7 or 13 fail
```

**Orchestration:** `gap-all.sh` is the nightly runner — it resolves versions, then runs each check by delegating to its step-registry `commands.sh` (the single source of check logic; `commands.sh` → `gap-*.py`), feature-gates last, and still fails on any standard check FAIL. It sets `GAP_FULL_REPORT=1` (default), so per-check HTML is skipped in CI; combined HTML aggregates all sections. Missing individual JSON is surfaced via `status-check-*.json` fallbacks in the combined report.

## Key Features

- **Automated extraction** - Uses `oc adm release extract` and Sippy API
- **Multi-format reports** - Per-check JSON, `status-check-*.json`, combined HTML/JSON
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
- Extracts CredentialsRequest manifests from release images to temporary directories
- Same approach as `osdctl iampermissions diff`
- Dynamically discovers files (no hardcoded lists)

**[managed-cluster-config](https://github.com/openshift/managed-cluster-config) Validation:**
- Uses `git clone --sparse-checkout` to efficiently fetch only needed directories
- Downloads only `resources/sts/{version}` or `resources/wif/{version}`
- Compares [managed-cluster-config](https://github.com/openshift/managed-cluster-config) policies against OCP release changes
- All file discovery is dynamic - no hardcoded file lists

**Feature Gates:**
- `https://sippy.dptools.openshift.org/api/feature_gates?release={version}`
- Queries Sippy API for feature gate data

**OCP Admin Gate Acknowledgments:**
- `https://github.com/openshift/cluster-version-operator` - Admin gate ConfigMaps
- [`https://github.com/openshift/managed-cluster-config`](https://github.com/openshift/managed-cluster-config) - Acknowledgment ConfigMaps

**Versions & Channels / Marketplace:**
- OCM CLI (`ocm list versions`) - Channel availability, ROSA Classic/OSD GCP marketplace (optional, graceful fallback)
- ROSA CLI (`rosa list versions --hosted-cp`) - ROSA HCP marketplace availability (optional, graceful fallback)
- Sippy API - GA version detection

**OCM Version Gates:**
- OCM API (`/api/clusters_mgmt/v1/version_gates`) via `ocm` CLI - Version gate configurations
- Auth: `OCM_TOKEN`, `OCM_CLIENT_ID`/`OCM_CLIENT_SECRET`, or `/var/run/ocm-token/token` (optional; graceful fallback)

**API Resources and CRD:**
- Prow GCS artifacts from live HCP, Classic, and OSD GCP cluster snapshots
- HCP, Classic, and OSD GCP live cluster discovery + CRD lists (OSD GCP skipped for 5.x)

**Critical Alerts:**
- Prow GCS artifacts from live HCP, Classic, and OSD GCP PrometheusRule snapshots
- Flattened PrometheusRule alerting rules (HCP, Classic, and OSD GCP; OSD GCP skipped for 5.x)

**Cluster Install, Target E2E, Upgrade E2E (checks 11–13):**
- Prow GCS: ClusterOperator/node snapshots, `junit-rosa-e2e.xml`, Y-1 upgrade periodics
- Consumed via `scripts/lib/prow_artifacts.py`; missing artifacts → SKIP (check 13 FAILs only on failed post-upgrade e2e or unhealthy COs)

## Implementation Details

**File Discovery:**
- OCP credential requests: Extracted to temporary directories, dynamically listed
- [managed-cluster-config](https://github.com/openshift/managed-cluster-config): Git sparse checkout to temporary directories
- No hardcoded file lists - everything discovered at runtime
- Efficient: Only downloads needed directories, not entire repositories

**Comparison Flow:**
1. Extract OCP release credential requests → temp directories
2. Sparse checkout [managed-cluster-config](https://github.com/openshift/managed-cluster-config) → temp directories
3. Compare files and actions between versions
4. Validate [managed-cluster-config](https://github.com/openshift/managed-cluster-config) matches OCP release changes
5. Cleanup all temporary directories

## Reports

**Formats:**
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
- [Development](development.md) - Contributing and customization
