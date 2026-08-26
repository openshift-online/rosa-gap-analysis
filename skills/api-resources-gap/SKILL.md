---
name: api-resources-gap
description: >
  Compare live ROSA API resources and CRDs between OpenShift versions using
  API Resources and CRD snapshots. Identifies new APIs, new CRDs,
  version changes, and deprecations. Informational; missing snapshots are SKIP.
compatibility:
  required_tools:
    - python3
    - curl (for Prow job-history and GCS artifact fetch)
---

# API Resources and CRD Gap Analysis

Compare the live Kubernetes/OpenShift API surface on ROSA clusters using
API Resources and CRD snapshots from Prow GCS. HCP, Classic, and OSD GCP,
each compared to itself. OSD GCP is skipped for OpenShift 5.x.

## When to Use

- Identifying new APIs or CRDs in a target OpenShift version
- Tracking API version promotions and deprecations
- Assessing managed-service impact of CRD changes
- After core nightlies have written snapshots of API Resources and CRDs to Prow GCS

## Workflow

1. Resolve baseline and target versions
2. Map each minor version + topology (hcp, classic, osd-gcp) to the core periodic job
3. Find the newest Prow build that contains `metadata.json` / `api-resources.json` / `crds.json`
4. Compare preferred API resources, all served versions, and CRDs
5. Generate HTML/JSON reports (informational; exit 0 even when snapshots are missing)

## Script Usage

```bash
python3 ./scripts/gap-api-resources.py --version 4.22
python3 ./scripts/gap-api-resources.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-api-resources.py --baseline 4.22 --target 5.0 --topology classic
python3 ./scripts/gap-api-resources.py --baseline-dir /tmp/base --target-dir /tmp/target --topology hcp
```

Via the orchestrator:

```bash
./scripts/gap-all.sh --version 4.22 --steps api-resources
```

## Data Source

Prow GCS artifacts from HCP, Classic, and OSD GCP core jobs. CI step `as:` name:

- `rosa-gap-analysis-api-resources-and-crd`

The step runs in the rosa-e2e **post** phase while the cluster is still up,
before deprovision. Files:

- `metadata.json`
- `api-resources.json`
- `crds.json`

HCP also writes the same files under `management/` from the Red Hat
management cluster (control plane). Hosted/guest files stay at the snapshot
root (customer data plane). Classic and OSD GCP are single-cluster topologies.

Jobs covered: daily HCP, Classic STS, and OSD GCP periodics.
OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Not HCP FIPS.
`--topology hcp` is HCP vs HCP (hosted + management when present).
`--topology classic` is Classic vs Classic. `--topology osd-gcp` is OSD GCP vs OSD GCP.
Prow channel: GA minors use the `staging-stable` job; pre-GA minors use
`staging-candidate` if that job has a snapshot, otherwise `staging-nightly`.

## Exit Codes

- `0` - Success, including SKIP when snapshots are missing
- `1` - Execution failure (invalid args, unexpected crash)
