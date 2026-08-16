---
name: e2e-validation-gap
description: >
  Validate target-version ROSA e2e results and alert monitoring from existing
  rosa-e2e JUnit. Standard check: failed tests FAIL; missing JUnit is SKIP.
  Alert monitoring is SKIP until VerifyNoCriticalAlerts exists in rosa-e2e.
compatibility:
  required_tools:
    - python3
    - curl (for Prow job-history and GCS artifact fetch)
---

# Target E2E Validation and alert monitoring

Consume `junit-rosa-e2e.xml` from the existing rosa-e2e test step. Target
version only — do not diff baseline vs target e2e.

## When to Use

- Confirming the target minor's latest HCP, Classic, and OSD GCP rosa-e2e JUnit is green
- Checking whether alert monitoring ran (SKIP until the rosa-e2e verifier lands)
- Running as part of `gap-all.sh` before Feature Gates

## Script Usage

```bash
python3 ./scripts/gap-e2e-validation.py --version 4.22
python3 ./scripts/gap-e2e-validation.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-e2e-validation.py --baseline 4.22 --target 5.0 --topology classic
python3 ./scripts/gap-e2e-validation.py --junit /tmp/junit-rosa-e2e.xml --topology hcp --baseline 4.21 --target 4.22
./scripts/gap-all.sh --version 4.22 --steps e2e-validation
```

`--baseline` is accepted for `gap-all.sh` compatibility. Only the **target**
JUnit is fetched.

## Data Source

Prow GCS artifact from HCP, Classic, and OSD GCP core jobs:

- Step `as:`: `rosa-e2e-test`
- File: `junit-rosa-e2e.xml` (under the step's nested `artifacts/` folder)

Jobs covered: daily HCP, Classic STS, and OSD GCP periodics.
OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Not HCP FIPS.
Fetches that topology's target JUnit.

Prow channel: GA minors use the `staging-stable` job; pre-GA minors use
`staging-candidate` if that job has JUnit, otherwise `staging-nightly`.

## Alert monitoring

Looks for a future Ginkgo test name containing one of:

- `should not have unexpected critical alerts firing`
- `VerifyNoCriticalAlerts`
- `no unexpected critical alerts`

Until that test exists in rosa-e2e (planned for September), the subsection is
**SKIP** and does not fail the check. If the test is present and failed, the
check **FAIL**s.

Do not treat Check #10 `alerts.json` as firing state — those are PrometheusRule
definitions only.

## Exit Codes

- `0` - PASS, or SKIP when JUnit is missing
- `1` - FAIL (e2e test failures or alert monitoring failure) or execution error
