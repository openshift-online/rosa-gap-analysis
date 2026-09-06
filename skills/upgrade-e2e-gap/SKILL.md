---
name: upgrade-e2e-gap
description: >
  Validate Y-1 → Y ROSA upgrades from existing rosa-e2e upgrade periodics.
  Standard check: failed post-upgrade e2e or unhealthy ClusterOperators FAIL;
  missing upgrade JUnit is SKIP. Covers HCP, Classic, and OSD GCP.
compatibility:
  required_tools:
    - python3
    - curl (for Prow job-history and GCS artifact fetch)
---

# Upgrade Validation from Y-1 to Y with E2E Tests

Consume post-upgrade `junit-rosa-e2e.xml` from rosa-e2e Y-minus-1 upgrade
jobs. Do not provision or upgrade clusters. Check #12 stays target-version
fresh-install JUnit.

## When to Use

- Confirming HCP and Classic STS upgrades from latest-stable Y-1 to Y candidate/RC
- Confirming OSD GCP upgrades on **4.x** paths (OSD GCP is not a 5.x product path)
- Reviewing post-upgrade e2e (workloads, storage, network, managed operators)
- Running as part of `gap-all.sh` after Check #12 and before Feature Gates

## Script Usage

```bash
python3 ./scripts/gap-upgrade-e2e.py --version 4.22
python3 ./scripts/gap-upgrade-e2e.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-upgrade-e2e.py --baseline 4.21 --target 4.22 --topology osd-gcp
# 5.x is AWS/STS-only: use HCP or Classic for upgrades into 5.0 (not OSD GCP)
python3 ./scripts/gap-upgrade-e2e.py --baseline 4.22 --target 5.0 --topology classic
python3 ./scripts/gap-upgrade-e2e.py --junit /tmp/junit-rosa-e2e.xml --topology hcp --baseline 4.21 --target 4.22
./scripts/gap-all.sh --version 4.22 --steps upgrade-e2e
```

## Data Source

Prow GCS artifacts from:

- `periodic-ci-openshift-online-rosa-e2e-main-upgrade-rosa-hcp-upgrade-staging-y-minus-1`
- `periodic-ci-openshift-online-rosa-e2e-main-upgrade-rosa-classic-sts-upgrade-staging-y-minus-1`
- `periodic-ci-openshift-online-rosa-e2e-main-upgrade-osd-gcp-upgrade-staging-y-minus-1`

Post-upgrade JUnit is required. Post-upgrade ClusterOperator health is
taken from JSON snapshots or `oc get co -o wide` txt dumps; a build is
used only when that post-upgrade minor matches the resolved target.
Duration comes from `upgrade-metrics.json` or `finished.json` timestamps.
Pre-upgrade CO snapshots (and CO deltas) are used when the upgrade step
published them; otherwise that subsection is SKIP.

Missing upgrade JUnit (including OSD GCP until that periodic publishes) is
SKIP. OpenShift **5.x is AWS/STS-only**, so OSD GCP → 5.x is not a supported
product path; use HCP/Classic for 5.0 upgrade examples. HCP/Classic → 5.0 is
covered when those upgrade periodics publish matching artifacts.

## Pass / Fail / Skip

- PASS: parsed JUnit has no failing tests; post-upgrade COs (when present) are healthy
- SKIP: upgrade JUnit missing or no matching target-minor job
- FAIL: failed e2e tests, post-upgrade snapshot shows degraded/unavailable COs, or a pre-upgrade snapshot shows the cluster was unhealthy before upgrade
- Duration / pre-upgrade COs missing: subsection SKIP, does not fail the check
