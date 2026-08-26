---
name: cluster-install-gap
description: >
  Compare live ROSA ClusterOperator and node install health between OpenShift
  versions using Cluster Install snapshots. Informational; missing snapshots
  are SKIP. Delete-duration metrics are not in the snapshot yet.
compatibility:
  required_tools:
    - python3
    - curl (for Prow job-history and GCS artifact fetch)
---

# Cluster Install and Delete Validation

Compare ClusterOperator and node health on ROSA clusters using Cluster Install
snapshots from Prow GCS. HCP, Classic, and OSD GCP, each compared to itself.
OSD GCP is skipped for OpenShift 5.x.

## When to Use

- Identifying newly degraded or unavailable ClusterOperators in a target version
- Tracking new/removed operators between OpenShift minors
- Checking node Ready status and node-count changes
- After core nightlies have written install-health snapshots to Prow GCS

## Script Usage

```bash
python3 ./scripts/gap-cluster-install.py --version 4.22
python3 ./scripts/gap-cluster-install.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-cluster-install.py --baseline 4.22 --target 5.0 --topology classic
python3 ./scripts/gap-cluster-install.py --baseline-dir /tmp/base --target-dir /tmp/target --topology hcp
./scripts/gap-all.sh --version 4.22 --steps cluster-install
```

## Data Source

Prow GCS artifacts from HCP, Classic, and OSD GCP core jobs. CI step `as:` name:

- `rosa-gap-analysis-cluster-install-delete-metrics`

The step runs in the rosa-e2e **post** phase while the cluster is still up,
before deprovision. Files:

- `metadata.json`
- `clusteroperators.json`
- `nodes.json`

Jobs covered: daily HCP, Classic STS, and OSD GCP periodics.
OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Not HCP FIPS.
`--topology hcp` is HCP vs HCP. `--topology classic` is Classic vs Classic.
`--topology osd-gcp` is OSD GCP vs OSD GCP.
HCP also writes the same files under `management/` from the Red Hat
management cluster (control plane). Hosted ClusterOperator/node health is
the CI step's PASS/FAIL source; management capture is informational.
Prow channel: GA minors use the `staging-stable` job; pre-GA minors use
`staging-candidate` if that job has a snapshot, otherwise `staging-nightly`.

The snapshot captures **install health**. Delete-duration metrics are not in
the snapshot yet.

## Exit Codes

- `0` - Success, including SKIP when snapshots are missing
- `1` - Execution failure
