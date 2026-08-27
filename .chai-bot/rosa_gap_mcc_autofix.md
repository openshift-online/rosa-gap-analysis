# Scheduled report: ROSA gap-analysis MCC autofix

You are running a **cron** scheduled task that watches ROSA gap-analysis Prow periodics and, on auto-fixable validation failures, opens **one pull request per failing OCP minor** against `openshift/managed-cluster-config` (MCC).

Follow global scheduled-task rules. End every turn with one of:
- `send_response(mode="report")` when you opened a PR, skipped because a PR already exists, or found a non-fixable failure the team should see
- `no_action_required(mode="report")` when every watched job's latest completed run is success/pending, or there is nothing to report

On-demand runs (`run_scheduled_task`) must always summarize results to the operator — do not call `no_action_required(mode="report")` for a manual run that found all-green jobs; give a short all-green summary instead.

## Goal

After the daily gap-analysis periodics finish, create MCC PRs for **CHECK #1–#5** failures (missing STS policies, WIF templates, acknowledgment files). Do **not** invent IAM JSON or WIF YAML.

Use the **same scripts as the laptop manual path**. The only difference is who opens the GitHub PR:

| Step | Human (laptop) | This task (chai-bot) |
|------|----------------|----------------------|
| Analyze failed job | `./ci/analyze-prow-failure.sh --job-name … --job-id … --keep-work-dir` | Same |
| Generate MCC files | `./ci/fix-prow-failure.sh --work-dir … --create-pr` | `./ci/fix-prow-failure.sh --work-dir … --generate-only` |
| Open MCC PR | `gh pr create` inside `fix-prow-failure.sh` | `priv_scm_create_change_request` after worker `make` + push |

Do **not** substitute `curl` / `download_ci_artifact` / hand-copied JSON for `analyze-prow-failure.sh`. That script downloads GCS artifacts with `gcloud` and writes `failure-summary.md`, the same as a human run.

## Discover jobs (regex — do not maintain a job list)

Match **periodics only**:

```
^periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-[0-9]+-[0-9]+$
```

Examples: `…-nightly-4-19`, `…-nightly-4-22`, `…-nightly-5-0`.

**Do not match:**
- presubmits (`pull-ci-openshift-online-rosa-gap-analysis-…`)
- lint jobs
- the retired name `periodic-ci-openshift-online-rosa-gap-analysis-main-nightly` (no `-periodics-`)

How to find them:
1. Query Prow (`search_prow_jobs` / job-history / the CI job-definitions DB) with prefix `periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-`
2. Or fetch `https://raw.githubusercontent.com/openshift/release/master/ci-operator/jobs/openshift-online/rosa-gap-analysis/openshift-online-rosa-gap-analysis-main-periodics.yaml` and keep `name:` values matching the regex

OCP minor comes from the suffix: `nightly-4-22` → `4.22`. MCC branch name is `ocp-4.22-gap-analysis-update`.

## Procedure

### 1. List jobs and latest completed runs

For each matching job, get the latest **completed** run (exclude PENDING). Record job name, build ID, result, Prow URL.

If every latest run is success (or pending/no data): cron → `no_action_required(mode="report")`. Manual run → short all-green summary via `send_response(mode="report")`.

### 2. Classify each failure

On the worker, after `analyze-prow-failure.sh`, read `gap-analysis-full_*.json` / `failure-summary.md`. Combined-report paths:

| Check | jq path |
|-------|---------|
| #1 AWS STS resources | `.aws_sts.validation_details.check_1_resources.status` |
| #2 AWS STS acks | `.aws_sts.validation_details.check_2_admin_ack.status` |
| #3 GCP WIF resources | `.gcp_wif.validation_details.check_1_resources.status` |
| #4 GCP WIF acks | `.gcp_wif.validation_details.check_2_admin_ack.status` |
| #5 OCP admin acks | `.ocp_gate_ack.validation_result` |

Permissions and files come from the JSON (`aws_sts.comparison.file_changes`, `actions.target_only`) — **not** from the branch name. Skip WIF generation for 5.x targets (AWS/STS-only).

| Result | Action |
|--------|--------|
| CHECK #1–#5 FAIL (missing STS/WIF/ack files) | Auto-fixable → continue |
| Only CHECK #6, #7, or #12 FAIL | Slack note, **no MCC PR** |
| CHECK #8–#11 only (informational) | Ignore |
| Missing artifacts / job error before reports | Slack note, **no MCC PR** |

### 3. Dedup — do not open a PR if one already exists

**Before** cloning, generating files, or calling `priv_scm_create_change_request`, search open PRs on `openshift/managed-cluster-config`:

```
is:pr is:open repo:openshift/managed-cluster-config
  (head:ocp-{minor}-gap-analysis-update OR "Add OCP {minor} Gap Analysis")
```

Skip if **any** open PR matches that OCP minor (any author, including `redhat-chai-bot` and `rosa-gap-analysis-bot`). Do not create a second PR, do not force-push, do not `gh pr edit`.

Closed or merged PRs do **not** block a new PR.

If skipped: note the existing PR URL in the report.

### 4. Generate files and open at most one PR per failing minor

For each auto-fixable failure with no existing PR (max **5** PRs per run, one per OCP minor):

1. `priv_scm_ensure_fork("github.com", "openshift/managed-cluster-config")`. Save `fork_repo`.
2. `rws_pod_create` with environment `general_dev`. The worker needs the **same tools as the laptop path**: `oc`, `gcloud`, `python3`, PyYAML, `jq`, `yq`, `git`, `make`. Install any that are missing. Do not generate policy JSON by hand.
3. `rws_new_agent` then `rws_query` (or a single `rws_goal_task`) to:
   - Clone `https://github.com/openshift-online/rosa-gap-analysis`
   - Analyze the failed job (same as a human):
     ```
     ./ci/analyze-prow-failure.sh --job-name <prow_job> --job-id <build_id> --keep-work-dir
     ```
     Last line of stdout is the work directory. Capture it. Do not skip this script.
   - If CHECK #1–#5 did not fail, stop for this minor (no generate, no PR).
   - Generate MCC files only (no GitHub PR from this script — that is the only flag difference from `--create-pr`):
     ```
     ./ci/fix-prow-failure.sh --work-dir <work_dir> --generate-only
     ```
   - Clone the chai-bot MCC fork from step 1 as `origin`, add `openshift/managed-cluster-config` as `upstream`, branch `ocp-{minor}-gap-analysis-update` from upstream default (`master`)
   - Copy generated files from `<work_dir>/managed-cluster-config/` onto the fork working tree
   - Run `make` in the MCC clone. If `make` fails or is not idempotent, **do not** push or open a PR
   - Scan the diff for secrets; commit; push the branch to the fork. Never force-push to a branch that already has a human commit. Never push to `openshift/managed-cluster-config` directly
4. Coordinator: `check_proposal` for `scm_create_change_request` on `openshift/managed-cluster-config`. This task is pre-authorized (`set_require: null`); on `permitted` immediately call `priv_scm_create_change_request` (not a draft):
   - `host=github.com`
   - `repo=openshift/managed-cluster-config`
   - `source_branch=ocp-{minor}-gap-analysis-update`
   - `target_branch=master`
   - `head_repo=<fork_repo>`
   - Title: `Add OCP {minor} Gap Analysis files`
   - Description must include: Prow job URL, HTML report URL, baseline → target, which checks failed, per-file added/removed IAM actions from the JSON, and that files were generated by rosa-gap-analysis `generate-fixes.py` (not hand-written)
5. Destroy the pod when done (`rws_pod_destroy`).

If generation fails, report the error and continue with the next minor. Do not open an empty or invalid PR.

### 5. Report

Call `send_response(mode="report")` with a short Slack `mrkdwn` summary:

```
*ROSA gap-analysis MCC autofix — {DATE}*

*PRs opened:* {N} ({links})
*Skipped (PR already exists):* {N} ({links})
*Not auto-fixable:* {N} ({job} — check 6/7/12 or missing artifacts)
```

Omit empty sections. Link Prow runs and MCC PRs. Do not include the `[Scheduled task: …]` metadata line.

If nothing was opened, skipped, or notable: cron → `no_action_required(mode="report")`.

## Constraints

- Never invent STS/WIF/ack file contents. Only `generate-fixes.py` output (plus MCC `make`).
- Never modify `app-interface`. MCC is allowed **only** for this task.
- Never auto-merge. Humans `/lgtm` and `/approve`.
- One open MCC PR per OCP minor. Skip if it already exists.
- Do not fold this into the rosa-e2e daily remediation workflow (that workflow must not touch MCC).
- `send_response()` ends the turn — no tool calls after it.
