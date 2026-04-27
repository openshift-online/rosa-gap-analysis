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

# Configuration
readonly DEFAULT_JOB_NAME="periodic-ci-openshift-online-rosa-gap-analysis-main-nightly"

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
  1. Analyze latest failed Prow job (analyze-prow-failure.sh)
  2. Generate fix files and validate (fix-prow-failure.sh)
  3. Create PR to managed-cluster-config

Temporary work directory is automatically created and cleaned up after PR creation.

WORKFLOW:
    Check job status → If failed: Download artifacts → Parse failures →
    Generate fixes → Validate → Create PR → Cleanup

OPTIONS:
    -j, --job-name NAME    Job name to analyze
                          (default: periodic-ci-openshift-online-rosa-gap-analysis-main-nightly)
    -i, --job-id ID        Specific job ID to analyze (skips latest check)
    -t, --test-mode        Create PR to TEST_REPO instead of production
    -d, --dry-run          Preview changes without creating PR
    -v, --verbose          Enable verbose output
    --web-auth            Authenticate via web browser if not logged in
    -h, --help            Display this help message

PREREQUISITES:
    - GH_TOKEN or GITHUB_TOKEN environment variable (REQUIRED)
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
    # Automated workflow: analyze latest failure and create PR
    $(basename "$0")

    # Analyze specific job and create PR
    $(basename "$0") --job-id 2041035894848229376

    # Test mode: create PR to test repository
    $(basename "$0") --test-mode

    # Dry run: preview without creating PR
    $(basename "$0") --dry-run

    # Verbose output
    $(basename "$0") --verbose

    # Authenticate via web browser if needed
    $(basename "$0") --web-auth

MANUAL WORKFLOW (for review/debugging):
    If you need to review artifacts before creating PR:
      ./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis
      # Review ~/prow-analysis/failure-summary.md
      ./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr

NOTES:
    - Uses temporary work directory (auto-cleaned after PR creation)
    - Checks most recent job status first (no unnecessary analysis)
    - Exits gracefully (exit 0) if most recent job is successful
    - Automatically validates generated files before PR creation
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

# Main workflow
main() {
    log_info "Prow Automated Fix Workflow"
    log_info "======================================================================"
    log_info ""

    parse_args "$@"

    # Use default job name if not specified
    local job_name="${JOB_NAME:-${DEFAULT_JOB_NAME}}"

    # Step 1: Check if there's a failed job to analyze
    # Skip this check if specific job ID is provided (user wants to analyze that specific job)
    if [ -z "${JOB_ID}" ]; then
        log_info "STEP 1/3: Checking job status..."
        log_info ""
        log_info "Checking most recent job for: ${job_name}..."

        # Get most recent job status
        local executions
        executions=$(get_job_executions "${job_name}" 1)

        local job_status
        job_status=$(echo "${executions}" | jq -r '.items[0].job_status')
        local latest_job_id
        latest_job_id=$(echo "${executions}" | jq -r '.items[0].id')

        log_info "Most recent job status: ${job_status} (ID: ${latest_job_id})"

        # If job is not failed, nothing to fix
        if [ "${job_status}" != "failure" ] && [ "${job_status}" != "error" ]; then
            log_info ""
            log_success "======================================================================"
            log_success "✓ Most recent job is ${job_status} - nothing to fix!"
            log_success "======================================================================"
            log_info ""
            log_info "To analyze a specific older failed job, use: --job-id <JOB_ID>"
            log_info "Find job IDs at: https://prow.ci.openshift.org/job-history/gs/test-platform-results/logs/${job_name}"
            exit 0
        fi

        log_info "Most recent job failed. Proceeding with analysis..."
        log_info ""
    fi

    # Step 2: Analyze the failed job
    log_info "STEP 2/3: Analyzing failed Prow job..."
    log_info ""

    local analyze_cmd=("${SCRIPT_DIR}/analyze-prow-failure.sh" "--keep-work-dir")

    if [ -n "${JOB_NAME}" ]; then
        analyze_cmd+=("--job-name" "${JOB_NAME}")
    fi

    if [ -n "${JOB_ID}" ]; then
        analyze_cmd+=("--job-id" "${JOB_ID}")
    fi

    if [ "${WEB_AUTH}" = true ]; then
        analyze_cmd+=("--web-auth")
    fi

    # Run analyze script and capture work directory from last line
    local analyze_output
    if ! analyze_output=$("${analyze_cmd[@]}" 2>&1); then
        log_error "Analysis failed!"
        echo "${analyze_output}" >&2
        exit 1
    fi

    echo "${analyze_output}"

    # Extract work directory from last line
    local work_dir
    work_dir=$(echo "${analyze_output}" | tail -1)

    if [ -z "${work_dir}" ] || [ ! -d "${work_dir}" ]; then
        log_error "Failed to get work directory from analyze script"
        log_error "Output: ${analyze_output}"
        exit 1
    fi

    log_info ""
    log_success "✓ Analysis complete. Work directory: ${work_dir}"
    log_info ""

    # Step 3: Generate fixes and create PR
    log_info "STEP 3/3: Generating fix files and creating pull request..."
    log_info ""

    local fix_cmd=("${SCRIPT_DIR}/fix-prow-failure.sh" "--work-dir" "${work_dir}")

    # Only add --create-pr if not in dry-run mode
    if [ "${DRY_RUN}" = false ]; then
        fix_cmd+=("--create-pr")
    else
        log_warn "DRY RUN: Skipping PR creation"
    fi

    if [ "${TEST_MODE}" = true ]; then
        fix_cmd+=("--test-mode")
    fi

    # Run fix script
    if ! "${fix_cmd[@]}"; then
        log_error "Fix and PR creation failed!"
        log_error "Work directory preserved for debugging: ${work_dir}"
        exit 1
    fi

    log_info ""
    log_success "======================================================================"
    log_success "✓ Automated workflow complete!"

    if [ "${DRY_RUN}" = false ]; then
        log_success "✓ Pull request created successfully"

        # Show PR URL if available (work directory may have been cleaned up)
        if [ -d "${work_dir}" ] && [ -f "${work_dir}/pr-url.txt" ]; then
            local pr_url
            pr_url=$(cat "${work_dir}/pr-url.txt")
            log_success "PR URL: ${pr_url}"
        fi
    else
        log_success "✓ Dry run complete (no PR created)"
        if [ -d "${work_dir}" ]; then
            log_info "Review generated files in: ${work_dir}"
        fi
    fi

    log_success "======================================================================"
    exit 0
}

main "$@"
