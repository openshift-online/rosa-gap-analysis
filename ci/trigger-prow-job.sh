#!/bin/bash

set -euo pipefail

# =============================================================================
# Script: trigger-job.sh
# Description: Trigger and monitor OpenShift CI Prow jobs via Gangway API
# Authentication: https://oauth-openshift.apps.ci.l2s4.p1.openshiftapps.com/oauth/token/display
# Usage: ./ci/prow/trigger-job.sh [OPTIONS]
# =============================================================================

# Configuration
readonly GANGWAY_URL="https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1"
readonly DEFAULT_JOB_NAME="periodic-ci-openshift-online-rosa-gap-analysis-main-nightly"
readonly JOB_EXECUTION_TYPE="1"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# Usage information
usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Trigger and monitor OpenShift CI Prow jobs via Gangway API.

OPTIONS:
    -j, --job-name NAME    Job name to trigger (default: ${DEFAULT_JOB_NAME})
    -w, --wait            Wait and poll for job completion
    -h, --help            Display this help message

EXAMPLES:
    # Trigger the default job
    $(basename "$0")

    # Trigger a specific job
    $(basename "$0") -j periodic-ci-openshift-online-rosa-gap-analysis-main-nightly

    # Trigger and wait for completion
    $(basename "$0") -w

AUTHENTICATION:
    Before running, authenticate at:
    https://oauth-openshift.apps.ci.l2s4.p1.openshiftapps.com/oauth/token/display

EOF
}

# Log functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*" >&2
}

# Check prerequisites
check_prerequisites() {
    local missing_deps=()

    if ! command -v oc &> /dev/null; then
        missing_deps+=("oc")
    fi

    if ! command -v jq &> /dev/null; then
        missing_deps+=("jq")
    fi

    if ! command -v curl &> /dev/null; then
        missing_deps+=("curl")
    fi

    if [ ${#missing_deps[@]} -ne 0 ]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        log_error "Please install the missing tools and try again."
        exit 1
    fi
}

# Validate authentication
validate_auth() {
    if ! oc whoami &> /dev/null; then
        log_error "Not authenticated to OpenShift CI."
        log_error "Please authenticate at: https://oauth-openshift.apps.ci.l2s4.p1.openshiftapps.com/oauth/token/display"
        exit 1
    fi

    local user
    user=$(oc whoami)
    log_info "Authenticated as: ${user}"
}

# Trigger Prow job
trigger_job() {
    local job_name="$1"
    local token
    token=$(oc whoami -t)

    log_info "Triggering job: ${job_name}"

    local response http_code
    response=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Authorization: Bearer ${token}" \
        "${GANGWAY_URL}/executions/" \
        -d "{\"job_name\": \"${job_name}\", \"job_execution_type\": \"${JOB_EXECUTION_TYPE}\"}")

    # Extract HTTP status code from last line
    http_code=$(echo "${response}" | tail -n1)
    response=$(echo "${response}" | sed '$d')

    # Check HTTP status code
    if [ "${http_code}" -ne 200 ] && [ "${http_code}" -ne 201 ]; then
        log_error "API request failed with HTTP ${http_code}"

        # Handle empty or whitespace-only responses
        if [ -z "${response}" ] || [ -z "$(echo "${response}" | tr -d '[:space:]')" ]; then
            case "${http_code}" in
                500)
                    log_error "Internal server error. The job name '${job_name}' may not exist or the API encountered an error."
                    log_error "Verify the job name is correct and exists in the OpenShift CI configuration."
                    ;;
                404)
                    log_error "Not found. The job '${job_name}' does not exist."
                    ;;
                401|403)
                    log_error "Authentication or authorization failed. Check your token or permissions."
                    ;;
                *)
                    log_error "No response body returned from the API."
                    ;;
            esac
        # Try to parse and display error message from response
        elif echo "${response}" | jq -e . >/dev/null 2>&1; then
            local error_msg
            error_msg=$(echo "${response}" | jq -r '.error // .message // "Unknown error"')
            log_error "Error: ${error_msg}"
            echo "${response}" | jq . >&2
        else
            log_error "Response: ${response}"
        fi
        exit 1
    fi

    # Try to parse job ID from response
    local job_id
    if ! job_id=$(echo "${response}" | jq -r .id 2>/dev/null); then
        log_error "Failed to parse response JSON"
        log_error "Response: ${response}"
        exit 1
    fi

    if [ -z "${job_id}" ] || [ "${job_id}" = "null" ]; then
        log_error "Failed to trigger job. No job ID returned."
        if echo "${response}" | jq -e . >/dev/null 2>&1; then
            echo "${response}" | jq . >&2
        else
            log_error "Response: ${response}"
        fi
        exit 1
    fi

    echo "${job_id}"
}

# Get job status
get_job_status() {
    local job_id="$1"
    local token
    token=$(oc whoami -t)

    curl -s -X GET \
        -H "Authorization: Bearer ${token}" \
        "${GANGWAY_URL}/executions/${job_id}"
}

# Wait for job completion
wait_for_job() {
    local job_id="$1"
    local poll_interval=30

    log_info "Waiting for job completion (polling every ${poll_interval}s)..."

    while true; do
        local status_json
        status_json=$(get_job_status "${job_id}")

        local state
        state=$(echo "${status_json}" | jq -r '.job_status // "unknown"')

        local timestamp=$(date +%H:%M:%S)

        case "${state}" in
            SUCCESS)
                log_info "${timestamp} Job completed successfully!"
                echo "${status_json}" | jq .
                return 0
                ;;
            FAILURE|ERROR|ABORTED)
                log_error "${timestamp} Job failed with status: ${state}"
                echo "${status_json}" | jq .
                return 1
                ;;
            PENDING)
                log_info "${timestamp} Job is running (PENDING)"
                sleep "${poll_interval}"
                ;;
            TRIGGERED)
                log_info "${timestamp} Job is starting (TRIGGERED)"
                sleep "${poll_interval}"
                ;;
            RUNNING)
                log_info "${timestamp} Job is running (RUNNING)"
                sleep "${poll_interval}"
                ;;
            *)
                log_warn "${timestamp} Unknown status: ${state}"
                sleep "${poll_interval}"
                ;;
        esac
    done
}

# Main function
main() {
    local job_name="${DEFAULT_JOB_NAME}"
    local wait_for_completion=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -j|--job-name)
                job_name="$2"
                shift 2
                ;;
            -w|--wait)
                wait_for_completion=true
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

    # Run prerequisite checks
    check_prerequisites
    validate_auth

    # Trigger the job
    local job_id
    job_id=$(trigger_job "${job_name}")

    log_info "Job triggered successfully!"
    log_info "Job ID: ${job_id}"

    # Get initial status
    log_info "Fetching job status..."
    local status_json
    status_json=$(get_job_status "${job_id}")
    echo "${status_json}" | jq .

    # Wait for completion if requested
    if [ "${wait_for_completion}" = true ]; then
        wait_for_job "${job_id}"
    fi
}

# Run main function
main "$@"
