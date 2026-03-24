# CI Build Root Image

This directory contains the Containerfile for the CI build-root image used by OpenShift CI (Prow/ci-operator) to run gap analysis jobs.

## Overview

The `Containerfile` defines a container image with all the tools required to run the gap analysis scripts in CI environments. This image is referenced by ci-operator configuration via `build_root.project_image.dockerfile_path`.

## Included Tools

| Tool | Version | Purpose |
|------|---------|---------|
| **oc CLI** | 4.21 (stable) | Extract CredentialsRequests from OpenShift release images |
| **jq** | System package | Process and compare JSON policy documents |
| **yq** | v4.52.4 | Parse YAML CredentialsRequest manifests |
| **Python 3** | System package | Run `parse-credentials-request.py` helper script |
| **PyYAML** | System package | Python YAML parsing library |
| **bash** | System package | Execute gap analysis shell scripts |
| **Gap Analysis Scripts** | Latest from repo | Pre-installed scripts for gap analysis workflows |

### Why These Tools?

- **oc CLI**: Required for `oc adm release extract --credentials-requests --cloud={aws,gcp}` to extract credential requests from release payloads
- **jq**: Processes and compares IAM/WIF policy JSON documents, extracts action-level differences
- **yq**: Alternative YAML parser (preferred over Python for performance)
- **Python 3 + PyYAML**: Fallback YAML parser used by `scripts/lib/parse-credentials-request.py`
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
  gap-aws-sts.sh --baseline 4.21 --target 4.22

# Or with full path
podman run --rm rosa-gap-analysis:latest \
  /gap-analysis/scripts/gap-aws-sts.sh --baseline 4.21 --target 4.22

# Run all gap analyses
podman run --rm rosa-gap-analysis:latest \
  gap-all.sh --baseline 4.21 --target 4.22

# Verify all tools are available
podman run --rm rosa-gap-analysis:latest bash -c "
  oc version --client &&
  jq --version &&
  yq --version &&
  python3 --version &&
  gap-aws-sts.sh --help
"
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
    # Scripts are pre-installed and in PATH
    gap-aws-sts.sh --baseline 4.21 --target 4.22
  container:
    from: src

- as: gap-analysis-all
  commands: |
    # Run all gap analyses (AWS STS and GCP WIF)
    gap-all.sh --baseline 4.21 --target 4.22
  container:
    from: src

- as: gap-analysis-nightly
  commands: |
    # Test against latest nightly
    TARGET_VERSION=NIGHTLY gap-all.sh
  container:
    from: src
```

The CI system:
1. Builds this Containerfile as the build root (includes scripts)
2. Scripts are pre-installed in `/gap-analysis/scripts/` and available in PATH
3. Runs test commands (gap analysis scripts)
4. Reports results based on exit codes (0 = pass, 1 = fail)

**Note**: Scripts are baked into the image, so no need to clone the repository or mount volumes during test execution.

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
/gap-analysis/                    # Working directory (WORKDIR)
├── scripts/                      # Gap analysis scripts (copied from repo)
│   ├── gap-all.sh               # Orchestrator script
│   ├── gap-aws-sts.sh           # AWS STS gap analysis
│   ├── gap-gcp-wif.sh           # GCP WIF gap analysis
│   └── lib/                     # Shared libraries
│       ├── common.sh            # Utilities
│       └── openshift-releases.sh # Version query library
```

**PATH Configuration**:
- `/gap-analysis/scripts/` is added to PATH
- `/gap-analysis/scripts/lib/` is added to PATH
- Scripts can be executed directly by name: `gap-all.sh`, `gap-aws-sts.sh`, etc.

**Working Directory**: `/gap-analysis`

## Related Documentation

- [Gap Analysis Scripts](../scripts/) - Scripts that run inside this container
- [Main README](../README.md) - Overall project documentation
- [ci-operator docs](https://docs.ci.openshift.org/docs/architecture/ci-operator/) - OpenShift CI system