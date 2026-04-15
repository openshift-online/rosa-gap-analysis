#!/bin/bash

# =============================================================================
# Script: analyze-prow-failure.sh
# Description: Analyze latest failed Prow job and identify validation failures
# Usage: ./ci/analyze-prow-failure.sh [--job-name JOB_NAME]
# =============================================================================

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source library functions
source "${SCRIPT_DIR}/lib/prow-api.sh"
source "${SCRIPT_DIR}/lib/failure-parser.sh"

# Configuration
readonly DEFAULT_JOB_NAME="periodic-ci-openshift-online-rosa-gap-analysis-main-nightly"
readonly DEFAULT_ARTIFACTS_DIR="${SCRIPT_DIR}/artifacts"  # Fallback only

# Colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

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

Analyze latest failed Prow job and identify validation failures.

This script:
  - Checks top 5 recent jobs for failures
  - Downloads gap-analysis artifacts from GCS using gcloud storage
  - Parses validation failures (CHECK #1-5)
  - Generates failure summary

BEHAVIOR:
  - Checks only the 5 most recent jobs for failures
  - If all 5 are successful: exits gracefully (no analysis needed)
  - If failed job found: downloads entire job directory and extracts reports
  - If failed job has no artifacts: tries next failed job
  - Use --job-id to analyze a specific job

OPTIONS:
    -j, --job-name NAME    Job name to analyze (default: ${DEFAULT_JOB_NAME})
    -i, --job-id ID        Specific job ID to analyze (skips top-5 check)
    -w, --work-dir DIR     Work directory for artifacts (default: /tmp/gap-analysis-XXXXXX)
    -k, --keep-work-dir    Keep temporary work directory after completion
    -h, --help            Display this help message

EXAMPLES:
    # Analyze latest failed job (checks top 5) - uses temp directory
    $(basename "$0")

    # Analyze and keep work directory for later review
    $(basename "$0") --keep-work-dir

    # Analyze specific failed job by ID
    $(basename "$0") --job-id 2043621071365607424

    # Use persistent directory for review
    $(basename "$0") --work-dir /home/user/prow-analysis

    # Analyze different job
    $(basename "$0") -j periodic-ci-openshift-online-rosa-gap-analysis-main-candidate

OUTPUT:
    Artifacts downloaded to work directory (printed at end):
    - gap-analysis-full_*.json  (Full JSON report)
    - gap-analysis-full_*.html  (HTML report)
    - gap-analysis-full_*.md    (Markdown report)
    - failure-summary.md        (Validation failure summary)

    Work directory path is printed on last line for use by fix-prow-failure.sh

PREREQUISITES:
    - oc: OpenShift CLI (authenticated)
    - jq: JSON processor
    - gcloud: Google Cloud SDK (for 'gcloud storage cp' command)
      Install from: https://cloud.google.com/sdk/docs/install

NEXT STEPS:
    After analysis, run fix-prow-failure to generate fix files and create PR.

    # Back-to-back workflow (uses same temp directory)
    WORK_DIR=\$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \\
      ./ci/fix-prow-failure.sh --work-dir "\$WORK_DIR" --create-pr

    # Manual workflow (review reports first)
    ./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis
    # Review reports, then:
    ./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr

EOF
}

# Check prerequisites
check_prerequisites() {
    local missing_deps=()

    for cmd in oc jq gcloud; do
        if ! command -v "${cmd}" &> /dev/null; then
            missing_deps+=("${cmd}")
        fi
    done

    if [ ${#missing_deps[@]} -ne 0 ]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        log_error "Please install the missing tools and try again."
        log_error ""
        log_error "For gcloud: Install gcloud SDK from https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    # Validate authentication
    if ! oc whoami &> /dev/null; then
        log_error "Not authenticated to OpenShift CI."
        log_error "Please authenticate at: https://oauth-openshift.apps.ci.l2s4.p1.openshiftapps.com/oauth/token/display"
        exit 1
    fi

    log_info "Authenticated as: $(oc whoami)"
}

# Download artifacts from GCS using gcloud storage
download_job_artifacts() {
    local job_name="$1"
    local job_id="$2"
    local output_dir="$3"

    log_info "Downloading job artifacts for ${job_id}..."

    # Create temporary directory for full job download
    local temp_dir
    temp_dir=$(mktemp -d)

    # Ensure cleanup on exit
    trap "rm -rf ${temp_dir}" EXIT

    # Download entire job directory
    log_info "Downloading from GCS: gs://test-platform-results/logs/${job_name}/${job_id}/"
    if ! download_job_directory_gcs "${job_name}" "${job_id}" "${temp_dir}"; then
        log_error "Failed to download job directory"
        rm -rf "${temp_dir}"
        return 1
    fi

    # Find gap-analysis reports in downloaded directory
    log_info "Finding gap-analysis reports in downloaded artifacts..."
    local reports
    reports=$(find_gap_analysis_reports "${temp_dir}/${job_id}" 2>&1)
    local find_exit_code=$?

    if [ ${find_exit_code} -ne 0 ] || [ -z "${reports}" ]; then
        log_error "No gap-analysis reports found in job artifacts"
        log_error "Job may have failed before gap-analysis ran"
        rm -rf "${temp_dir}"
        return 1
    fi

    # Create output directory
    mkdir -p "${output_dir}"

    # Copy found reports to output directory
    local downloaded_count=0
    while IFS= read -r report_path; do
        local filename
        filename=$(basename "${report_path}")
        local output_path="${output_dir}/${filename}"

        if cp "${report_path}" "${output_path}"; then
            log_success "Copied: ${filename}"
            ((downloaded_count++))
        else
            log_warn "Failed to copy: ${filename}"
        fi
    done <<< "${reports}"

    # Also copy prowjob.json for job metadata (used by fix-prow-failure.sh)
    local prowjob_json="${temp_dir}/${job_id}/prowjob.json"
    if [ -f "${prowjob_json}" ]; then
        if cp "${prowjob_json}" "${output_dir}/prowjob.json"; then
            log_info "Copied prowjob metadata"
        fi
    fi

    # Cleanup temp directory
    rm -rf "${temp_dir}"

    if [ ${downloaded_count} -eq 0 ]; then
        log_error "Failed to copy any report files"
        return 1
    fi

    log_success "Downloaded ${downloaded_count} gap-analysis report(s)"
}

# Analyze gap report and generate PR summary
analyze_gap_report() {
    local artifacts_dir="$1"
    local job_id="$2"

    log_info "Analyzing gap analysis report..."

    # Find the JSON report
    local json_report
    json_report=$(find "${artifacts_dir}" -name "gap-analysis-full_*.json" -type f | head -1)

    if [ -z "${json_report}" ] || [ ! -f "${json_report}" ]; then
        log_error "Gap analysis JSON report not found in ${artifacts_dir}"
        return 1
    fi

    log_info "Found report: ${json_report}"

    # Parse report
    local report_data
    report_data=$(parse_gap_report "${json_report}")

    if [ -z "${report_data}" ]; then
        log_error "Failed to parse gap analysis report"
        return 1
    fi

    local baseline target
    baseline=$(echo "${report_data}" | jq -r '.baseline')
    target=$(echo "${report_data}" | jq -r '.target')

    log_info "Baseline: ${baseline}"
    log_info "Target: ${target}"

    # Generate failure summary
    local summary_path="${artifacts_dir}/failure-summary.md"
    log_info "Generating failure summary..."

    generate_failure_summary "${json_report}" "${job_id}" "${summary_path}"

    log_success "Failure summary generated: ${summary_path}"

    # Display summary
    echo ""
    echo "======================================================================"
    cat "${summary_path}"
    echo "======================================================================"
}

# Main function
main() {
    local job_name="${DEFAULT_JOB_NAME}"
    local specific_job_id=""
    local work_dir=""
    local keep_work_dir=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -j|--job-name)
                job_name="$2"
                shift 2
                ;;
            -i|--job-id)
                specific_job_id="$2"
                shift 2
                ;;
            -w|--work-dir)
                work_dir="$2"
                shift 2
                ;;
            -k|--keep-work-dir)
                keep_work_dir=true
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

    # Create work directory
    local created_temp=false
    if [ -z "${work_dir}" ]; then
        # Create temporary directory in /tmp
        work_dir=$(mktemp -d -t gap-analysis-XXXXXX)
        created_temp=true
        log_info "Created temporary work directory: ${work_dir}"
    else
        # User specified directory
        mkdir -p "${work_dir}"
        log_info "Using work directory: ${work_dir}"
    fi

    # Setup cleanup trap if temp directory should be deleted
    if [ "${created_temp}" = true ] && [ "${keep_work_dir}" = false ]; then
        trap "rm -rf '${work_dir}'" EXIT
        log_info "Temporary directory will be cleaned up on exit (use --keep-work-dir to preserve)"
    fi

    log_info "Gap Analysis Failure Analyzer"
    log_info "======================================================================"

    # Check prerequisites
    check_prerequisites

    local job_id=""
    local artifacts_downloaded=false

    # If specific job ID provided, use it directly
    if [ -n "${specific_job_id}" ]; then
        log_info "Using specified job ID: ${specific_job_id}"
        job_id="${specific_job_id}"

        # Get job metadata
        local job_metadata
        job_metadata=$(get_job_metadata "${job_id}")

        if [ -n "${job_metadata}" ]; then
            echo "${job_metadata}" | jq .
        fi

        # Try to download artifacts
        if download_job_artifacts "${job_name}" "${job_id}" "${work_dir}"; then
            artifacts_downloaded=true
            log_success "Downloaded artifacts from job: ${job_id}"
        else
            log_error "Failed to download artifacts from job ${job_id}"
            log_error "Check if the job has gap-analysis artifacts"
            exit 1
        fi
    else
        # Find latest failed job in top 5 jobs
        log_info "Finding latest failed job for: ${job_name} (checking top 5 jobs)..."

        # Get top 5 jobs
        local executions
        executions=$(get_job_executions "${job_name}" 5)

        # Check if any failed
        local failed_jobs
        failed_jobs=$(echo "${executions}" | jq -r '.items[] | select(.job_status == "failure" or .job_status == "error") | .id')

        if [ -z "${failed_jobs}" ]; then
            log_success "✅ No failed jobs in the last 5 executions"
            log_info ""
            log_info "Recent job statuses:"
            echo "${executions}" | jq -r '.items[] | "  - Job \(.id): \(.job_status)"'
            log_info ""
            log_info "All recent jobs are successful or pending. No analysis needed."
            log_info "To analyze a specific failed job, use: --job-id <JOB_ID>"
            log_info "Find job IDs at: https://prow.ci.openshift.org/job-history/gs/test-platform-results/logs/${job_name}"
            exit 0
        fi

        # Try each failed job until we find one with artifacts
        while IFS= read -r candidate_job_id; do
            log_info "Trying failed job: ${candidate_job_id}"

            # Get job metadata
            local job_metadata
            job_metadata=$(get_job_metadata "${candidate_job_id}")

            if [ -n "${job_metadata}" ]; then
                echo "${job_metadata}" | jq .
            fi

            # Try to download artifacts
            if download_job_artifacts "${job_name}" "${candidate_job_id}" "${work_dir}"; then
                job_id="${candidate_job_id}"
                artifacts_downloaded=true
                log_success "Found failed job with artifacts: ${job_id}"
                break
            else
                log_warn "Job ${candidate_job_id} has no gap-analysis artifacts, trying next..."
            fi
        done <<< "${failed_jobs}"

        if [ "${artifacts_downloaded}" = false ]; then
            log_error "No failed jobs with gap-analysis artifacts found in top 5 executions"
            log_error "Recent failed jobs may have failed before gap-analysis ran"
            log_error ""
            log_error "To analyze a specific failed job with artifacts:"
            log_error "  1. Find job ID at: https://prow.ci.openshift.org/?job=${job_name}"
            log_error "  2. Run: $(basename "$0") --job-id <JOB_ID>"
            exit 1
        fi
    fi

    # Analyze gap report
    analyze_gap_report "${work_dir}" "${job_id}"

    log_success ""
    log_success "======================================================================"
    log_success "✅ Analysis complete!"
    log_success "======================================================================"
    log_success "Work directory: ${work_dir}/"
    log_success "Failure summary: ${work_dir}/failure-summary.md"
    log_success ""

    if [ "${keep_work_dir}" = true ] || [ "${created_temp}" = false ]; then
        log_success "Work directory preserved for review or fix-prow-failure.sh"
        log_success ""
        log_success "Next step: Run fix-prow-failure to generate fix files and create PR"
        log_success "  ./ci/fix-prow-failure.sh --work-dir \"${work_dir}\" --create-pr"
    else
        log_warn "Temporary directory will be cleaned up on exit"
        log_warn "Use --keep-work-dir to preserve it for fix-prow-failure.sh"
    fi

    # Print work directory path on last line for easy capture in scripts
    echo "${work_dir}"
}

# Run main function
main "$@"
