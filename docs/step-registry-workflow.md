# Gap Analysis Step-Registry Workflow

This documents the ci-operator **step registry** implementation of the gap-analysis
job ([ROSAENG-15179](https://redhat.atlassian.net/browse/ROSAENG-15179)): the
`scripts/gap-all.sh` job expressed as discrete, independently-runnable,
composable steps in the openshift/release step-registry format.

It provides two workflows:
**aggregated** (full validation + combined report) and **independent** (every check
runs on its own and produces its own per-check report).

GA readiness validation (`ga-validation`) is **not part of any CI workflow** — it is
a standalone step run manually/individually by SREs (see
[ga-readiness-validation.md](ga-readiness-validation.md)).

Source lives at `ci-operator/step-registry/rosa/gap-analysis/` (mirror of the
openshift/release layout, to be contributed upstream).

## `gap-all.sh` and nightlies

Nightly periodics keep running **`scripts/gap-all.sh`** (Prow is unchanged). To avoid
two copies of the check logic, `gap-all.sh` no longer calls the `gap-*.py` analyzers
directly — it is the single-pod runner that **delegates to the same step-registry
`commands.sh`** defined here. `commands.sh` → `gap-*.py` is therefore the one source of
truth for every check, shared by both the nightly (`gap-all.sh`) and the ci-operator
workflows.

`gap-all.sh` keeps the behavior nightlies depend on and delegates only the checks:

- **Stays in `gap-all.sh`:** argument parsing, `--steps`, `--dry-run`; version resolution
  (including `BASE_VERSION`/`TARGET_VERSION` and the `NIGHTLY`/`CANDIDATE` keywords, which
  the `resolve-versions` ref does not understand) — after resolving it writes
  `${SHARED_DIR}/gap-versions.env` in the same format the checks source; OCM login via
  `ocm_authenticate` (an in-container login the check scripts inherit, rather than the
  `ocm-auth` ref's token file); the combined report; the final summary; and the exit code.
- **Delegated:** `run_all_steps` calls `scripts/run-workflow.py`, which reads the
  aggregated workflow YAML, expands the `rosa-gap-analysis-checks` chain, and reads each
  ref YAML's `commands:` — so the chain and ref YAML (not a hardcoded list) decide which
  checks run and in what order, feature-gates last. `gap-all.sh` then executes each
  resolved `commands.sh`, honoring `--steps`, running every selected check even after a
  standard check fails, then exits 1 if any standard check failed.
- GA readiness stays out: its ref is not in the workflow/chain, so `run-workflow.py`
  never emits it.

This stays one Prow step with one log. Separate pods per check only happen when
openshift/release runs the `rosa-gap-analysis-aggregated` workflow itself.

## Why a step registry

- **Debuggability** — each check is its own ci-operator step with its own pod,
  logs, and exit code, so you can see (and re-run) exactly which check failed.
- **Reusability / composability** — refs can be added, removed, or reordered in
  any workflow; chains bundle them; workflows wire pre/test/post.
- **Clear contracts** — steps exchange state through files, not in-memory globals.

## Steps (refs)

Lifecycle:

| Ref | Phase | Purpose |
|-----|-------|---------|
| `rosa-gap-analysis-setup` | pre | Validate prerequisites (python3/jq), init `${SHARED_DIR}/gap-analysis-reports`, clear stale state |
| `rosa-gap-analysis-ocm-auth` | pre | Validate OCM login via `scripts/lib/ocm_auth.sh` using `OCM_CLIENT_ID`/`OCM_CLIENT_SECRET` read from the `rosa-e2e`/`gap-analysis` credential collection mounted at `/var/run/ocm-credentials` (keys `sso-client-id`, `sso-client-secret`); stage a token at `${SHARED_DIR}/ocm-token` when one is provided (graceful no-op if no creds) |
| `rosa-gap-analysis-resolve-versions` | pre | Resolve `BASELINE`/`TARGET` once; write `${SHARED_DIR}/gap-versions.env` (safe `printf %q`); emit `GAP_SKIP=1` to skip gracefully |
| `rosa-gap-analysis-report` | post | Aggregate per-check reports into the combined HTML/JSON report |
| `rosa-gap-analysis-cleanup` | post | Remove staged secrets/scratch (`ocm-token`, `gap-versions.env`) and analyzer temp dirs |

Checks (one ref per global gap-analysis check; mapping to `scripts/gap-*.py`):

| Ref | Check | Script | Type |
|-----|-------|--------|------|
| `rosa-gap-analysis-aws-sts` | 1-2 | gap-aws-sts.py | standard |
| `rosa-gap-analysis-gcp-wif` | 3-4 | gap-gcp-wif.py | standard |
| `rosa-gap-analysis-ocp-gate-ack` | 5 | gap-ocp-gate-ack.py | standard |
| `rosa-gap-analysis-versions-channels` | 6 | gap-versions-channels.py | standard |
| `rosa-gap-analysis-ocm-version-gate` | 7 | gap-ocm-version-gate.py | standard |
| `rosa-gap-analysis-api-resources` | 9 | gap-api-resources.py | informational |
| `rosa-gap-analysis-critical-alerts-diff` | 10 | gap-critical-alerts.py | informational |
| `rosa-gap-analysis-cluster-install` | 11 | gap-cluster-install.py | informational |
| `rosa-gap-analysis-e2e-validation` | 12 | gap-e2e-validation.py | informational |
| `rosa-gap-analysis-upgrade-e2e` | 13 | gap-upgrade-e2e.py | standard |
| `rosa-gap-analysis-feature-gates` | 8 | gap-feature-gates.py | informational (runs **last**) |

> `critical-alerts-diff` is named to avoid colliding with the existing **capture**
> ref `rosa-gap-analysis-critical-alerts` (see "Capture vs analysis" below).

Plus a standalone, **individual-only** GA-readiness ref — intentionally **not** in
any workflow or the `rosa-gap-analysis-checks` chain (GA readiness is run manually by
SREs, not by CI):

| Ref | Script | Type |
|-----|--------|------|
| `rosa-gap-analysis-ga-validation` | scripts/prod/gap-ga-validation.py | standalone GA-readiness; self-reporting detailed report; **run individually only, never part of a CI workflow** |

## Chain and workflows

- **Chain** `rosa-gap-analysis-checks` — all 11 checks in `gap-all.sh` order
  (1-7, then 9-13, feature-gates #8 last). Drop it into any workflow's `test`, or
  inline the refs to add/remove/reorder.

Two workflows cover the CI gap-analysis modes (both without cluster provisioning).
Each check ref self-reports (its `gap-*.py` writes per-check HTML+JSON), and the
`report` ref renders from whatever checks are present, so a report can be produced
for a single check or any subset.

1. **`rosa-gap-analysis-aggregated`** — full validation + combined report.
   - `pre`: setup → ocm-auth → resolve-versions
   - `post`: `rosa-gap-analysis-checks` chain → report (combined) → cleanup
2. **`rosa-gap-analysis-independent`** — every check runs independently and
   produces its own per-check report; no combined aggregation.
   - `pre`: setup → ocm-auth → resolve-versions
   - `post`: `rosa-gap-analysis-checks` chain (each ref self-reports) → cleanup

The checks run in `post` (not `test`) so every check runs even if an earlier one
fails; a standard-check FAIL still fails the job, and report/cleanup run afterward.

GA readiness is intentionally **not** a workflow: `rosa-gap-analysis-ga-validation`
is run individually only (manually by SREs), never wired into a CI workflow or the
chain.

## Step contract

Steps are configured entirely through environment variables and exchange state
through `${SHARED_DIR}`; artifacts go to `${ARTIFACT_DIR}`.

| Variable | Produced by | Consumed by | Meaning |
|----------|-------------|-------------|---------|
| `${SHARED_DIR}/gap-versions.env` | resolve-versions | checks, report | `GAP_SKIP`, `BASELINE`, `TARGET` (shell-quoted) |
| `/var/run/ocm-credentials/{sso-client-id,sso-client-secret}` | `rosa-e2e`/`gap-analysis` credential collection (`credentials:` mount) | ocm-auth, checks | OCM creds; each step loads them into `OCM_CLIENT_ID`/`OCM_CLIENT_SECRET` and logs in via `scripts/lib/ocm_auth.sh` (`ocm_load_credentials` + `ocm_authenticate`) |
| `${SHARED_DIR}/ocm-token` | ocm-auth | checks | back-compat token for `ocm login` (staged only when a token was provided) |
| `${SHARED_DIR}/gap-analysis-reports` | checks | report | per-check JSON/HTML + status files |
| `${ARTIFACT_DIR}` | every step | CI | per-step artifacts + per-step logs |
| `OPENSHIFT_VERSION` / `BASELINE` / `TARGET` | job env | resolve-versions, checks | version inputs (precedence: OPENSHIFT_VERSION > BASELINE+TARGET > auto-detect) |
| `OCM_LOGIN_ENV` | job env | ocm-auth, checks | OCM environment (default `staging`) |
| `GAP_VERBOSE` | job env / `gap-all.sh --verbose` | checks | `1` = pass `--verbose` to the analyzer (extra console detail) |

**Exit semantics** map to ci-operator per-step: standard checks exit non-zero on
validation FAIL (failing the step/job); informational checks exit 0 on findings
and non-zero only on execution error; `report` never owns the verdict.
The checks run in `post` (not `test`): `post` steps all run regardless of earlier
failures, so one failed check does not skip the rest, while a standard check's
non-zero exit still fails the job.

## Running checks individually

Every check is an independent ref that produces its **own** per-check report
(HTML+JSON) — you can run one, a subset, or all of them without any aggregation.

**In CI:** use the `rosa-gap-analysis-independent` workflow (runs every check as its
own step, each self-reporting). To run only a subset, inline just the refs you want
from the `rosa-gap-analysis-checks` chain into a workflow's `test` phase — add,
remove, or reorder freely.

**Check step names** (directory = ref `rosa-gap-analysis-<name>`):
`aws-sts`, `gcp-wif`, `ocp-gate-ack`, `versions-channels`, `ocm-version-gate`,
`api-resources`, `critical-alerts-diff`, `cluster-install`, `e2e-validation`,
`upgrade-e2e`, `feature-gates` — plus `ga-validation` (GA readiness).

**Locally**, each `commands.sh` defaults `GAP_SCRIPTS_DIR` to the image path
`/gap-analysis/scripts`; override it to run against this repo's `scripts/`
(use a `python3` that has `PyYAML`+`Jinja2`, as the image does):

```bash
export GAP_SCRIPTS_DIR="$PWD/scripts"
export SHARED_DIR=$(mktemp -d) ARTIFACT_DIR=$(mktemp -d)
REG=ci-operator/step-registry/rosa/gap-analysis

# (optional) resolve BASELINE/TARGET once -> $SHARED_DIR/gap-versions.env, which
# every check then reads automatically:
BASELINE=4.21.15 TARGET=4.22.0-rc.3 "$REG"/resolve-versions/rosa-gap-analysis-resolve-versions-commands.sh

# run ANY single check (swap aws-sts for any name above):
check=aws-sts
"$REG/$check/rosa-gap-analysis-$check-commands.sh"

# the check writes its own report here (and copies it to $ARTIFACT_DIR):
ls "$SHARED_DIR/gap-analysis-reports"/gap-analysis-*.{html,json}
```

A check can also take versions directly instead of the resolve step:

```bash
OPENSHIFT_VERSION=4.22 "$REG"/feature-gates/rosa-gap-analysis-feature-gates-commands.sh
# or: BASELINE=4.21.15 TARGET=4.22.0-rc.3 "$REG"/aws-sts/rosa-gap-analysis-aws-sts-commands.sh
```

To build the combined report from whatever checks ran, run the report step after:

```bash
"$REG"/report/rosa-gap-analysis-report-commands.sh
```

(Standalone, without the registry, you can also run the analyzers directly:
`python3 ./scripts/gap-aws-sts.py --version 4.22` — see
[getting-started.md](getting-started.md).)

## Image requirement

All refs use `from: gap-analysis` — an image with python3 + the `scripts/gap-*.py`
analyzers (and ideally `ocm`/`rosa` for the OCM/ROSA-backed checks), built from this
repo's `ci/Containerfile`. The consuming ci-operator config must make that image
available (e.g. via `base_images`/`images`). Wiring a ci-operator config/job that
uses one of the workflows (`rosa-gap-analysis-aggregated` / `-independent`) is
tracked separately.

In CI, the job checks out the full repo (`from: src`), so `gap-all.sh` and the check
`commands.sh` are available there regardless. `ci/Containerfile` **also** copies
`ci-operator/` into the image so running the image standalone (e.g. `podman run …
gap-all.sh …`, see [`gap-all.sh` and nightlies](#gap-allsh-and-nightlies)) works too.
The `commands.sh` default `GAP_SCRIPTS_DIR` to `/gap-analysis/scripts`; `gap-all.sh`
locates the registry via `REGISTRY_DIR` (default
`${PROJECT_ROOT}/ci-operator/step-registry/rosa/gap-analysis`).

## Capture vs analysis

The openshift/release `rosa/gap-analysis` registry already contains **capture**
refs (`api-resources-and-crd`, `critical-alerts`, `cluster-install-delete-metrics`)
that snapshot a **live** ROSA cluster in e2e workflows' `post` phase and upload to
Prow GCS. The refs here are the **analysis** side: they read those GCS
snapshots/JUnit (no cluster) and run the gap comparison. The two are complementary
and intentionally distinct.

## Validation

```bash
# shell + yaml/json + naming
shellcheck --severity=error ci-operator/step-registry/rosa/gap-analysis/*/*-commands.sh
# authoritative registry validation (in an openshift/release checkout):
make validate-step-registry   # or run ci-operator-configresolver --registry ... --validate-only
```
