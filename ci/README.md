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

## Manually Triggering Prow Jobs

The `run-prow-job.sh` script allows you to manually trigger and monitor OpenShift CI Prow jobs via the Gangway API.

### Prerequisites

1. **Required tools**: `oc`, `jq`, `curl`
2. **Authentication**: Authenticate to OpenShift CI cluster at:
   ```
   https://oauth-openshift.apps.ci.l2s4.p1.openshiftapps.com/oauth/token/display
   ```

### Usage

```bash
./run-prow-job.sh [OPTIONS]
```

**Options:**
- `-j, --job-name NAME` - Specify the Prow job name to trigger (default: `periodic-ci-openshift-online-rosa-gap-analysis-main-nightly`)
- `-w, --wait` - Wait and poll for job completion with status updates
- `-h, --help` - Display help message

### Examples

**Trigger the default nightly job:**
```bash
./run-prow-job.sh
```

**Trigger and wait for completion:**
```bash
./run-prow-job.sh -w
```

**Trigger a specific job:**
```bash
./run-prow-job.sh -j periodic-ci-openshift-online-rosa-gap-analysis-main-nightly
```

**Trigger a specific job and monitor until completion:**
```bash
./run-prow-job.sh -j periodic-ci-openshift-online-rosa-gap-analysis-main-nightly -w
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

## Related Documentation

- [Gap Analysis Scripts](../scripts/) - Scripts that run inside this container
- [Main README](../README.md) - Overall project documentation
- [ci-operator docs](https://docs.ci.openshift.org/docs/architecture/ci-operator/) - OpenShift CI system