#!/bin/bash

# =============================================================================
# Script: prow-autofix.sh
# Description: One-step automated Prow failure analysis and PR creation
# Usage: ./ci/prow-autofix.sh [OPTIONS]
# =============================================================================
#
# This script combines analyze-prow-failure.sh and fix-prow-failure.sh into
# a single automated workflow:
#   1. Analyze latest failed Prow job
#   2. Generate fix files
#   3. Create PR to managed-cluster-config
#
# Temporary work directory is automatically created and cleaned up.
# =============================================================================

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source library functions
source "${SCRIPT_DIR}/lib/prow-api.sh"

# Colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

# Default values
JOB_NAME=""
JOB_ID=""
TEST_MODE=false
DRY_RUN=false
GENERATE_ONLY=false
SKIP_IF_PR_EXISTS=false
VERBOSE=false
WEB_AUTH=false

# Log functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

# Usage information
usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

One-step automated Prow failure analysis and PR creation.

This script automates the complete workflow:
  1. Analyze latest failed Prow job(s) (analyze-prow-failure.sh)
  2. Generate fix files and validate (fix-prow-failure.sh)
  3. Create PR to managed-cluster-config (unless --generate-only / --dry-run)

With no --job-name, discovers periodics matching
  ^periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-[0-9]+-[0-9]+$
and processes each whose latest completed run failed.

Temporary work directory is automatically created and cleaned up after PR creation.

OPTIONS:
    -j, --job-name NAME     Job name to analyze (omit to process all matching periodics)
    -i, --job-id ID         Specific job ID to analyze (skips latest check)
    -t, --test-mode         Create PR to TEST_REPO instead of production
    -d, --dry-run           Preview changes without creating PR
    --generate-only         Generate MCC files only; do not create a GitHub PR
    --skip-if-pr-exists     Exit successfully if an open MCC PR already exists for that OCP minor
    -v, --verbose           Enable verbose output
    --web-auth              Authenticate via web browser if not logged in
    -h, --help              Display this help message

PREREQUISITES:
    - GH_TOKEN or GITHUB_TOKEN (REQUIRED unless --generate-only or --dry-run)
    - gcloud CLI authenticated (for GCS artifact downloads)
    - gh CLI installed (for PR creation)
    - oc, python3, PyYAML, jq, yq installed

CONFIGURATION:
    All configuration uses standard defaults from ci/pr-defaults.sh:
      TARGET_REPO="openshift/managed-cluster-config"
      FORK_REPO="rosa-gap-analysis-bot/managed-cluster-config"
      GITHUB_USERNAME="rosa-gap-analysis-bot"

    Override via environment variables or command-line flags if needed.

EXAMPLES:
    # Process every matching periodic whose latest run failed
    $(basename "$0")

    # Generate MCC files only (no GitHub PR). Same analyze+fix path as a human; chai-bot uses this instead of --create-pr.
    $(basename "$0") --job-name periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-4-22 --generate-only

    # Skip if an MCC PR for that minor is already open
    $(basename "$0") --skip-if-pr-exists

    # Analyze specific job and create PR
    $(basename "$0") --job-name periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-4-22 --job-id 2041035894848229376

    # Test mode: create PR to test repository
    $(basename "$0") --test-mode

    # Dry run: preview without creating PR
    $(basename "$0") --dry-run

MANUAL WORKFLOW (for review/debugging):
    If you need to review artifacts before creating PR:
      ./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis
      # Review ~/prow-analysis/failure-summary.md
      ./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr

NOTES:
    - Uses temporary work directory (auto-cleaned after PR creation)
    - Checks most recent job status first (no unnecessary analysis)
    - Exits gracefully (exit 0) if no matching periodics failed
    - --skip-if-pr-exists does not update or replace an existing open PR
    - Use --job-id to analyze specific older failed jobs (skips status check)

EOF
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -j|--job-name)
                JOB_NAME="$2"
                shift 2
                ;;
            -i|--job-id)
                JOB_ID="$2"
                shift 2
                ;;
            -t|--test-mode)
                TEST_MODE=true
                shift
                ;;
            -d|--dry-run)
                DRY_RUN=true
                shift
                ;;
            --generate-only)
                GENERATE_ONLY=true
                shift
                ;;
            --skip-if-pr-exists)
                SKIP_IF_PR_EXISTS=true
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            --web-auth)
                WEB_AUTH=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
}

# Analyze one job and generate fixes / PR.
process_one_job() {
    local job_name="$1"
    local job_id="${2:-}"

    log_info "Analyzing ${job_name}${job_id:+ (ID: ${job_id})}..."
    log_info ""

    local analyze_cmd=("${SCRIPT_DIR}/analyze-prow-failure.sh" "--keep-work-dir" "--job-name" "${job_name}")

    if [ -n "${job_id}" ]; then
        analyze_cmd+=("--job-id" "${job_id}")
    fi

    if [ "${WEB_AUTH}" = true ]; then
        analyze_cmd+=("--web-auth")
    fi

    local analyze_output
    if ! analyze_output=$("${analyze_cmd[@]}" 2>&1); then
        log_error "Analysis failed for ${job_name}!"
        echo "${analyze_output}" >&2
        return 1
    fi

    echo "${analyze_output}"

    local work_dir
    work_dir=$(echo "${analyze_output}" | tail -1)

    if [ -z "${work_dir}" ] || [ ! -d "${work_dir}" ]; then
        log_error "Failed to get work directory from analyze script for ${job_name}"
        log_error "Output: ${analyze_output}"
        return 1
    fi

    log_info ""
    log_success "✓ Analysis complete. Work directory: ${work_dir}"
    log_info ""

    log_info "Generating fix files${GENERATE_ONLY:+ (generate-only)}${DRY_RUN:+ (dry-run)}..."
    log_info ""

    local fix_cmd=("${SCRIPT_DIR}/fix-prow-failure.sh" "--work-dir" "${work_dir}")

    if [ "${GENERATE_ONLY}" = true ]; then
        fix_cmd+=("--generate-only")
        log_warn "GENERATE ONLY: Skipping PR creation"
    elif [ "${DRY_RUN}" = true ]; then
        log_warn "DRY RUN: Skipping PR creation"
    else
        fix_cmd+=("--create-pr")
    fi

    if [ "${SKIP_IF_PR_EXISTS}" = true ]; then
        fix_cmd+=("--skip-if-pr-exists")
    fi

    if [ "${TEST_MODE}" = true ]; then
        fix_cmd+=("--test-mode")
    fi

    if ! "${fix_cmd[@]}"; then
        log_error "Fix / PR step failed for ${job_name}!"
        log_error "Work directory preserved for debugging: ${work_dir}"
        return 1
    fi

    if [ "${DRY_RUN}" = false ] && [ "${GENERATE_ONLY}" = false ]; then
        if [ -d "${work_dir}" ] && [ -f "${work_dir}/pr-url.txt" ]; then
            log_success "PR URL: $(cat "${work_dir}/pr-url.txt")"
        fi
    elif [ "${GENERATE_ONLY}" = true ] && [ -d "${work_dir}" ]; then
        log_success "Generated files: ${work_dir}/managed-cluster-config/"
    elif [ "${DRY_RUN}" = true ] && [ -d "${work_dir}" ]; then
        log_info "Review generated files in: ${work_dir}"
    fi

    return 0
}

# Main workflow
main() {
    parse_args "$@"

    log_info "Prow Automated Fix Workflow"
    log_info "======================================================================"
    log_info ""

    local -a jobs_to_process=()
    local -a job_ids_to_process=()
    local lookup_failures=0

    if [ -n "${JOB_ID}" ]; then
        local job_name="${JOB_NAME}"
        if [ -z "${job_name}" ]; then
            log_info "Resolving job name for build ID ${JOB_ID}..."
            if ! job_name=$(resolve_job_name_for_id "${JOB_ID}"); then
                log_error "Pass --job-name along with --job-id, or use a build from a matching periodic."
                exit 1
            fi
        fi
        jobs_to_process+=("${job_name}")
        job_ids_to_process+=("${JOB_ID}")
    elif [ -n "${JOB_NAME}" ]; then
        log_info "Checking most recent job for: ${JOB_NAME}..."
        local executions job_status latest_job_id
        executions=$(get_job_executions "${JOB_NAME}" 1)
        job_status=$(echo "${executions}" | jq -r '.items[0].job_status // empty')
        latest_job_id=$(echo "${executions}" | jq -r '.items[0].id // empty')
        log_info "Most recent job status: ${job_status} (ID: ${latest_job_id})"
        if [ "${job_status}" != "failure" ] && [ "${job_status}" != "error" ]; then
            log_success "Most recent job is ${job_status:-unknown} - nothing to fix!"
            exit 0
        fi
        jobs_to_process+=("${JOB_NAME}")
        job_ids_to_process+=("")
    else
        local jobs job executions job_status job_id
        jobs=$(list_gap_analysis_periodic_jobs) || exit 1
        log_info "Discovered gap-analysis periodics. Checking latest completed run of each..."
        while IFS= read -r job; do
            [ -z "${job}" ] && continue
            if ! executions=$(get_job_executions "${job}" 1); then
                log_error "Failed to fetch job history for ${job}"
                lookup_failures=$((lookup_failures + 1))
                continue
            fi
            job_status=$(echo "${executions}" | jq -r '.items[0].job_status // empty')
            job_id=$(echo "${executions}" | jq -r '.items[0].id // empty')
            log_info "  ${job}: ${job_status:-no-data} (${job_id:-n/a})"
            if [ "${job_status}" = "failure" ] || [ "${job_status}" = "error" ]; then
                jobs_to_process+=("${job}")
                job_ids_to_process+=("")
            fi
        done <<< "${jobs}"

        if [ "${lookup_failures}" -gt 0 ] && [ ${#jobs_to_process[@]} -eq 0 ]; then
            log_error "Failed to query job history for ${lookup_failures} periodic(s); not treating as a clean run."
            exit 1
        fi

        if [ ${#jobs_to_process[@]} -eq 0 ]; then
            log_success "No latest-run failures among matching periodics - nothing to fix!"
            exit 0
        fi
        if [ "${lookup_failures}" -gt 0 ]; then
            log_warn "Continuing with ${#jobs_to_process[@]} failed job(s); ${lookup_failures} periodic(s) could not be queried."
        fi
    fi

    local i failures=0
    for i in "${!jobs_to_process[@]}"; do
        log_info ""
        log_info "----------------------------------------------------------------------"
        if ! process_one_job "${jobs_to_process[$i]}" "${job_ids_to_process[$i]}"; then
            failures=$((failures + 1))
        fi
    done

    log_info ""
    log_success "======================================================================"
    if [ "${failures}" -gt 0 ] || [ "${lookup_failures}" -gt 0 ]; then
        log_error "Completed with ${failures} failure(s) out of ${#jobs_to_process[@]} job(s)${lookup_failures:+; ${lookup_failures} history lookup(s) failed}."
        exit 1
    fi
    log_success "✓ Automated workflow complete (${#jobs_to_process[@]} job(s))!"
    log_success "======================================================================"
    exit 0
}

main "$@"
