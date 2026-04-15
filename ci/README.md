# CI Build Root Image

This directory contains the Containerfile for the CI build-root image used by OpenShift CI (Prow/ci-operator) to run gap analysis jobs.

## Overview

The `Containerfile` defines a container image with all the tools required to run the gap analysis scripts in CI environments. This image is referenced by ci-operator configuration via `build_root.project_image.dockerfile_path`.

## Included Tools

| Tool | Version | Purpose |
|------|---------|---------|
| **oc CLI** | 4.21 (stable) | Extract CredentialsRequests from OpenShift release images |
| **Python 3** | System package | Main runtime for gap analysis scripts |
| **PyYAML** | System package | YAML parsing for credential requests and configuration |
| **curl** | System package | Fetch data from Sippy API (releases, feature gates) |
| **bash** | System package | Execute gap-all.sh orchestrator script |
| **Gap Analysis Scripts** | Latest from repo | Pre-installed Python and bash scripts for gap analysis workflows |

### Why These Tools?

- **oc CLI**: Required for `oc adm release extract --credentials-requests --cloud={aws,gcp}` to extract credential requests from release payloads
- **Python 3 + PyYAML**: Main runtime for gap analysis scripts (gap-aws-sts.py, gap-gcp-wif.py, gap-feature-gates.py), YAML processing, report generation
- **curl**: Fetches release data and feature gates from Sippy API
- **bash**: Orchestrator script (gap-all.sh) that calls Python analysis scripts and generates combined reports
- **Gap Analysis Scripts**: Pre-installed in `/gap-analysis/scripts/` and added to PATH for direct execution

## Base Image

```dockerfile
FROM registry.access.redhat.com/ubi9/ubi:latest
```

Using Red Hat Universal Base Image (UBI) 9 for:
- Official Red Hat support and security updates
- Compatibility with OpenShift CI infrastructure
- Smaller attack surface compared to general-purpose base images

## OpenShift-Specific Considerations

```dockerfile
# Pre-create cache directories writable by any UID
RUN mkdir -p /tmp/.cache /tmp/gap-analysis-data && \
    chmod -R 777 /tmp/.cache /tmp/gap-analysis-data

ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache
```

OpenShift runs containers with **random UIDs** for security. These configurations ensure:
- Scripts can write temporary files regardless of assigned UID
- `oc` CLI can cache release metadata
- Gap analysis scripts can create temporary comparison files

## Local Testing

### Build the Image

```bash
# From repository root
podman build -f ci/Containerfile -t rosa-gap-analysis:latest .
```

### Test the Image

```bash
# Run gap analysis in the container (scripts are pre-installed)
podman run --rm rosa-gap-analysis:latest \
  gap-all.sh --baseline 4.21 --target 4.22

# Individual Python scripts
podman run --rm rosa-gap-analysis:latest \
  python3 /gap-analysis/scripts/gap-aws-sts.py --baseline 4.21 --target 4.22

podman run --rm rosa-gap-analysis:latest \
  python3 /gap-analysis/scripts/gap-feature-gates.py --baseline 4.21 --target 4.22

# Verify all tools are available
podman run --rm rosa-gap-analysis:latest bash -c "
  oc version --client &&
  python3 --version &&
  python3 -c 'import yaml; print(\"PyYAML OK\")' &&
  curl --version &&
  gap-all.sh --help
"

# Test with report generation (mount volume to access reports)
podman run --rm -v $(pwd)/reports:/gap-analysis/reports rosa-gap-analysis:latest \
  gap-all.sh --baseline 4.21 --target 4.22
ls -lh reports/
```

## CI Integration

This image is used by Prow/ci-operator jobs defined in `.prow/` (when added). Example usage:

```yaml
# In ci-operator config
build_root:
  project_image:
    dockerfile_path: ci/Containerfile

tests:
- as: gap-analysis-aws
  commands: |
    # Scripts are pre-installed, generates reports in ./reports/
    python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
    ls -lh reports/
  container:
    from: src

- as: gap-analysis-feature-gates
  commands: |
    # Feature gates analysis with Sippy API
    python3 ./scripts/gap-feature-gates.py --baseline 4.21 --target 4.22
    cat reports/gap-analysis-feature-gates_*.md
  container:
    from: src

- as: gap-analysis-all
  commands: |
    # Run all gap analyses (AWS STS, GCP WIF, and Feature Gates)
    # Generates individual and combined reports
    gap-all.sh --baseline 4.21 --target 4.22
    ls -lh reports/
  container:
    from: src

- as: gap-analysis-nightly
  commands: |
    # Test against latest nightly
    TARGET_VERSION=NIGHTLY gap-all.sh
    # Reports saved to ./reports/ with timestamped filenames
  container:
    from: src

- as: gap-analysis-with-artifacts
  commands: |
    # Generate reports in CI artifacts directory
    mkdir -p ${ARTIFACT_DIR}/gap-reports
    REPORT_DIR=${ARTIFACT_DIR}/gap-reports gap-all.sh
  container:
    from: src
```

The CI system:
1. Builds this Containerfile as the build root (includes scripts)
2. Scripts are pre-installed in `/gap-analysis/scripts/` and available in PATH
3. Runs test commands (Python gap analysis scripts for AWS STS, GCP WIF, and Feature Gates)
4. Scripts automatically generate reports in MD, HTML, and JSON formats
5. Scripts exit 0 on successful execution (regardless of policy or feature gate differences)
6. Scripts only exit 1 on execution failures (missing tools, network errors, etc.)
7. Reports can be saved to `${ARTIFACT_DIR}` for CI artifact collection

**Note**: Scripts are baked into the image, so no need to clone the repository or mount volumes during test execution. Policy and feature gate differences are logged to stdout/stderr and saved to comprehensive reports, but don't cause test failures.

## Updating Tool Versions

### Update oc CLI Version

```dockerfile
ARG OC_VERSION=4.22  # Change this
```

**When to update**: When analyzing newer OpenShift versions that require a newer oc CLI.

### Update yq Version

```dockerfile
ARG YQ_VERSION=v4.53.0  # Change this
```

Check latest releases: https://github.com/mikefarah/yq/releases

## Testing updates

1. Build image locally with changes
2. Run all gap analysis scripts in container
3. Verify CI jobs pass before merging

## Container Image Structure

The container image has the following structure:

```
/gap-analysis/                       # Working directory (WORKDIR)
├── scripts/                         # Gap analysis scripts (copied from repo)
│   ├── gap-all.sh                  # Orchestrator script (bash)
│   ├── gap-aws-sts.py              # AWS STS gap analysis (Python)
│   ├── gap-gcp-wif.py              # GCP WIF gap analysis (Python)
│   ├── gap-feature-gates.py        # Feature gate gap analysis (Python)
│   ├── generate-combined-report.py # Combined report generator (Python)
│   └── lib/                        # Shared libraries
│       ├── common.py               # Python utilities (logging, etc.)
│       ├── openshift_releases.py   # Version resolution (Python)
│       ├── reporters.py            # Report generation (MD, HTML, JSON)
│       ├── common.sh               # Bash utilities
│       └── openshift-releases.sh   # Version resolution (Bash)
├── reports/                         # Default report directory (created at runtime)
│   ├── gap-analysis-aws-sts_*.md
│   ├── gap-analysis-aws-sts_*.html
│   ├── gap-analysis-aws-sts_*.json
│   ├── gap-analysis-gcp-wif_*.{md,html,json}
│   ├── gap-analysis-feature-gates_*.{md,html,json}
│   └── gap-analysis-full_*.{md,html,json}  # Combined report
```

**PATH Configuration**:
- `/gap-analysis/scripts/` is added to PATH
- `/gap-analysis/scripts/lib/` is added to PATH
- Scripts can be executed directly by name: `gap-all.sh`, `python3 gap-aws-sts.py`, etc.

**Working Directory**: `/gap-analysis`

**Report Generation**:
- All scripts automatically generate reports in `./reports/` by default
- Override with `--report-dir` flag or `REPORT_DIR` environment variable
- Reports include MD (human-readable), HTML (web-viewable), and JSON (machine-readable) formats

## CI Organization

The `ci/` directory is organized into functional subdirectories:

```
ci/
├── analyze-prow-failure.sh     # Analyze failed jobs
├── fix-prow-failure.sh          # Generate fixes and create PRs
├── trigger-prow-job.sh          # Manually trigger Prow jobs
├── lib/                         # Shared CI libraries
│   ├── prow-api.sh              # Prow deck API functions
│   ├── failure-parser.sh        # JSON report parsing
│   ├── generate-fixes.py        # File content generation
│   └── validate-wif-template.sh # WIF template validation
├── templates/                   # PR description templates
│   └── pr-body.md               # PR template with placeholders
├── artifacts/                   # Downloaded artifacts (gitignored)
└── Containerfile                # CI build root image
```

### Integration

- **analyze-prow-failure.sh**: Downloads artifacts, parses failures, generates summary
- **fix-prow-failure.sh**: Generates fixes, validates, creates PR to managed-cluster-config
- **trigger-prow-job.sh**: Triggers Prow jobs via Gangway API

## Analyzing CI Failures

The `prow/analyze-failure.sh` script automatically analyzes failed Prow jobs and generates PR requirements for managed-cluster-config.

### Prerequisites

1. **Required tools**: `oc`, `jq`, `gcloud`
   - `oc`: OpenShift CLI (for authentication validation)
   - `jq`: JSON processor
   - `gcloud`: Google Cloud SDK (for artifact downloads via `gcloud storage cp`)
     - Install from: https://cloud.google.com/sdk/docs/install
2. **Authentication**: The script validates authentication via `oc whoami` but Prow deck API calls don't require an authentication token. Authenticate to OpenShift CI cluster at:
   ```
   https://oauth-openshift.apps.ci.l2s4.p1.openshiftapps.com/oauth/token/display
   ```

### Usage

```bash
./ci/prow/analyze-failure.sh [OPTIONS]
```

**Options:**
- `-j, --job-name NAME` - Specify the Prow job name to analyze (default: `periodic-ci-openshift-online-rosa-gap-analysis-main-nightly`)
- `-i, --job-id ID` - Analyze a specific job by ID (skips top-5 job check)
- `-h, --help` - Display help message

### What It Does

1. **Finds latest FAILED job** - Checks top 5 recent jobs for failures; exits gracefully if all are successful/pending
2. **Downloads artifacts** - Uses `gcloud storage cp -r` to download entire job directory from GCS to `ci/artifacts/`
3. **Extracts reports** - Finds gap-analysis reports in `artifacts/test/artifacts/rosa-gap-analysis-reports/`
4. **Parses failures** - Extracts validation errors from CHECK #1-5
5. **Generates failure summary** - Creates `ci/artifacts/failure-summary.md` with validation failures

### Behavior

- **Top 5 check**: Only checks the 5 most recent job executions for failures
- **Graceful exit**: If all top 5 jobs are successful or pending, exits with informational message
- **Artifact download**: Downloads entire job directory using `gcloud storage cp -r`
- **Specific job analysis**: Use `--job-id` flag to analyze a specific failed job (bypasses top-5 check)
- **Artifact retry**: If a failed job has no artifacts, tries the next failed job in top 5

### Examples

**Example 1: Analyze latest failed job (checks top 5)**
```bash
./ci/prow/analyze-failure.sh

# Output when failures found:
# [INFO] Gap Analysis Failure Analyzer
# ======================================================================
# [INFO] Authenticated as: user@redhat.com
# [INFO] Finding latest failed job for: periodic-ci-openshift-online-rosa-gap-analysis-main-nightly (checking top 5 jobs)...
# [INFO] Trying failed job: 2041035894848229376
# {
#   "id": "2041035894848229376",
#   "job_status": "failure",
#   "started": "2026-04-06T06:10:49Z",
#   "finished": "2026-04-06T06:17:27Z"
# }
# [INFO] Downloading job artifacts for 2041035894848229376...
# [INFO] Downloading from GCS: gs://test-platform-results/logs/.../2041035894848229376/
# [INFO] Finding gap-analysis reports in downloaded artifacts...
# [SUCCESS] Copied: gap-analysis-full_4.21.9_to_4.22.0-ec.4_20260406_061719.json
# [SUCCESS] Copied: gap-analysis-full_4.21.9_to_4.22.0-ec.4_20260406_061719.html
# [SUCCESS] Downloaded 2 gap-analysis report(s)
# [SUCCESS] Found failed job with artifacts: 2041035894848229376
# [INFO] Analyzing gap analysis report...
# [INFO] Found report: ci/artifacts/gap-analysis-full_4.21.9_to_4.22.0-ec.4_20260406_061719.json
# [INFO] Baseline: 4.21.9
# [INFO] Target: 4.22.0-ec.4
# [INFO] Generating failure summary...
# [SUCCESS] Failure summary generated: ci/artifacts/failure-summary.md
#
# ======================================================================
# [Summary output displayed here]
# ======================================================================
#
# [SUCCESS] ======================================================================
# [SUCCESS] ✅ Analysis complete!
# [SUCCESS] ======================================================================
# [SUCCESS] Artifacts downloaded: ci/artifacts/
# [SUCCESS] Failure summary: ci/artifacts/failure-summary.md
```

**Example 2: All recent jobs successful (graceful exit)**
```bash
./ci/prow/analyze-failure.sh

# Output:
# [INFO] Finding latest failed job for: periodic-ci-openshift-online-rosa-gap-analysis-main-nightly (checking top 5 jobs)...
# [SUCCESS] ✅ No failed jobs in the last 5 executions
# [INFO] 
# [INFO] Recent job statuses:
#   - Job 2043621071365607424: success
#   - Job 2043335702826917888: success
#   - Job 2043050334288228352: success
#   - Job 2042764965749538816: pending
#   - Job 2042479597210849280: success
# [INFO]
# [INFO] All recent jobs are successful or pending. No analysis needed.
# [INFO] To analyze a specific failed job, use: --job-id <JOB_ID>
# [INFO] Find job IDs at: https://prow.ci.openshift.org/?job=periodic-ci-openshift-online-rosa-gap-analysis-main-nightly
```

**Example 3: Analyze specific job by ID**
```bash
./ci/prow/analyze-failure.sh --job-id 2041035894848229376

# Output:
# [INFO] Using specified job ID: 2041035894848229376
# [INFO] Downloading job artifacts for 2041035894848229376...
# [SUCCESS] Downloaded artifacts from job: 2041035894848229376
# [INFO] Analyzing gap analysis report...
# [SUCCESS] ✅ Analysis complete!
```

### Output Files

All files are saved to `ci/artifacts/`:

- **gap-analysis-full_*.json** - Full JSON report from failed job
- **gap-analysis-full_*.html** - HTML report (if available)
- **gap-analysis-full_*.md** - Markdown report (if available)
- **failure-summary.md** - Generated validation failure summary

### Failure Summary Content

The generated `failure-summary.md` includes:

1. **Job metadata** - Job ID, baseline/target versions
2. **Validation failures by check**:
   - AWS STS (CHECK #1 & #2) - Missing resources and acknowledgment files
   - GCP WIF (CHECK #3 & #4) - Missing templates and acknowledgment files
   - OCP Admin Gates (CHECK #5) - Missing acknowledgment files
3. **Added/removed items** - Lists changes that caused failures
4. **Next steps** - Guidance to run `fix-prow-failure.sh` to generate fix files

### Example Failure Summary

```markdown
# Gap Analysis Failure Summary

**Job ID:** 2041035894848229376
**Baseline Version:** 4.21.9
**Target Version:** 4.22.0-ec.4

---

## Validation Failures

### CHECK #1: AWS STS Policy Files (FAILED)

**Missing Directory:**
- `resources/sts/4.22/`

**Missing Policy Files:**
- `resources/sts/4.22/openshift-cluster-csi-drivers-ebs-cloud-credentials.json`
- `resources/sts/4.22/openshift-ingress-operator-cloud-credentials.json`
- [... 5 more files ...]

**Added AWS Permissions (2):**
- `ec2:AllocateHosts`
- `ec2:ReleaseHosts`

### CHECK #2: AWS STS Acknowledgments (FAILED)

**Missing Acknowledgment Files:**
- `deploy/osd-cluster-acks/sts/4.22/config.yaml`
- `deploy/osd-cluster-acks/sts/4.22/osd-sts-ack_CloudCredential.yaml`

[... GCP WIF and OCP sections ...]

---

## Next Steps

Run the fix script to generate missing files and create PR:

\`\`\`bash
./ci/fix-prow-failure.sh --create-pr
\`\`\`

This will:
1. Generate all missing policy and acknowledgment files
2. Create a PR to managed-cluster-config with the fixes
```

### Library Functions

The analyzer uses library modules organized under `ci/prow/lib/`:

**ci/prow/lib/api.sh** - Prow deck API integration:
- Uses Prow deck API at `https://prow.ci.openshift.org/prowjobs.js` (publicly accessible, no auth required)
- `get_job_executions()` - Get recent job executions (default: top 5)
- `get_job_metadata()` - Fetch job details (status, timestamps)
- `download_job_directory_gcs()` - Download entire job directory using `gcloud storage cp -r`
- `find_gap_analysis_reports()` - Find gap-analysis reports in downloaded artifacts directory

**ci/prow/lib/parser.sh** - JSON report parsing:
- `parse_gap_report()` - Extract baseline, target, validation results
- `extract_aws_sts_failures()` - Parse AWS STS validation errors
- `extract_gcp_wif_failures()` - Parse GCP WIF validation errors
- `extract_ocp_gate_failures()` - Parse OCP gate acknowledgment errors
- `generate_failure_summary()` - Generate failure summary markdown

**ci/lib/generate-fixes.py** - File content generation (used by `fix-prow-failure.sh`):
- Reads gap-analysis JSON report
- Extracts credential requests from OCP release using `oc adm release extract`
- Generates AWS STS policy files (JSON format matching managed-cluster-config)
- Generates GCP WIF template (YAML format)
- Generates acknowledgment files (config.yaml, CloudCredential patches)
- Validates all generated files

## Manually Triggering Prow Jobs

The `prow/trigger-job.sh` script allows you to manually trigger OpenShift CI Prow jobs via the Gangway API and monitor their status.

### Prerequisites

1. **Required tools**: `oc`, `jq`, `curl`
2. **Authentication**: Authenticate to OpenShift CI cluster at:
   ```
   https://oauth-openshift.apps.ci.l2s4.p1.openshiftapps.com/oauth/token/display
   ```

### Usage

```bash
./ci/prow/trigger-job.sh [OPTIONS]
```

**Options:**
- `-j, --job-name NAME` - Specify the Prow job name to trigger (default: `periodic-ci-openshift-online-rosa-gap-analysis-main-nightly`)
- `-w, --wait` - Wait and poll for job completion with status updates
- `-h, --help` - Display help message

### Examples

**Trigger the default nightly job:**
```bash
./ci/prow/trigger-job.sh
```

**Trigger and wait for completion:**
```bash
./ci/prow/trigger-job.sh -w
```

**Trigger a specific job:**
```bash
./ci/prow/trigger-job.sh -j periodic-ci-openshift-online-rosa-gap-analysis-main-nightly
```

**Trigger a specific job and monitor until completion:**
```bash
./ci/prow/trigger-job.sh -j periodic-ci-openshift-online-rosa-gap-analysis-main-nightly -w
```

### Output

**Without `-w` flag:**
- Displays job ID and initial job status as JSON

**With `-w` flag:**
- Polls job status every 30 seconds
- Shows timestamped status updates:
  ```
  [INFO] 14:23:05 Job is starting (TRIGGERED)
  [INFO] 14:23:35 Job is running (PENDING)
  [INFO] 14:24:05 Job is running (PENDING)
  [INFO] 14:28:45 Job completed successfully!
  ```
- Displays final JSON payload when job completes or fails

### Job Status Values

- **TRIGGERED** - Job has been triggered and is initializing
- **PENDING** - Job is actively running (working on backend)
- **SUCCESS** - Job completed successfully
- **FAILURE** - Job failed
- **ERROR** - Job encountered an error
- **ABORTED** - Job was aborted

### Error Handling

The script validates:
- Required dependencies (oc, jq, curl)
- Authentication status
- API response codes and error messages
- Job name existence (returns meaningful error for non-existent jobs)

## Fixing Prow Failures and Creating PRs

Automates generating fix files and creating PRs to managed-cluster-config.

### Quick Start

**Prerequisites:** 
- `python3`, `PyYAML`, `jq`, `yq`, `gh` CLI, `GH_TOKEN` env var
- `yq` required for WIF template validation

**Back-to-back workflow (recommended):**
```bash
# Analyze and create PR (temp dir auto-cleaned)
WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \
  ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr
```

**Manual review:**
```bash
# Step 1: Analyze
./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis

# Step 2: Review
cat ~/prow-analysis/failure-summary.md

# Step 3: Fix and create PR
./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr
```

### What It Does

1. **Generates files:** AWS STS policies, GCP WIF templates, acknowledgment files
2. **Validates files:**
   - JSON/YAML syntax validation
   - WIF template validation (service account ID ≤25 chars, role ID ≤50 chars, format checks)
3. **Creates PR** with branch `ocp-X.XX-gap-analysis-update` and description including:
   - Prow job URL: `[View Job Details](https://prow.ci.openshift.org/view/gs/test-platform-results/logs/{job_name}/{job_id})`
   - HTML report URL: `[View Full Report](https://gcsweb-ci.../{exact_filename}.html)`
   - Per-file permission changes: `**filename:** Added: ec2:AllocateHosts, ec2:ReleaseHosts`
   - Conditional OCP ack files (only if admin gates exist)
   - File counts and footer: "Generated by [ROSA Gap Analysis](https://github.com/openshift-online/rosa-gap-analysis)"

### Configuration

Set `GH_TOKEN` environment variable or create `.github-pr-config`:
```bash
export GH_TOKEN="ghp_yourToken"
TARGET_REPO="openshift/managed-cluster-config"
FORK_REPO="bot-user/managed-cluster-config"
```

See `ci/TESTING.md` for detailed testing guide.

## Related Documentation

- [Gap Analysis Scripts](../scripts/) - Scripts that run inside this container
- [CI Testing Guide](TESTING.md) - End-to-end testing workflow
- [Main README](../README.md) - Overall project documentation

## Related Documentation

- [Gap Analysis Scripts](../scripts/) - Scripts that run inside this container
- [CI Testing Guide](TESTING.md) - End-to-end testing workflow
- [Main README](../README.md) - Overall project documentation
- [ci-operator docs](https://docs.ci.openshift.org/docs/architecture/ci-operator/) - OpenShift CI system