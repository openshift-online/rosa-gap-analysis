#!/bin/bash

# =============================================================================
# Library: api.sh
# Description: Helper functions for querying Prow job history and GCS artifacts
# Note: Uses Prow job-history page (prow.ci.openshift.org/job-history/...) for job list
#       No authentication required (publicly accessible)
# =============================================================================

set -euo pipefail

# Configuration
GANGWAY_URL="${GANGWAY_URL:-https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1}"
PROW_URL="${PROW_URL:-https://prow.ci.openshift.org}"
GCS_BASE_URL="${GCS_BASE_URL:-https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/test-platform-results/logs}"
DEFAULT_JOB_NAME="${DEFAULT_JOB_NAME:-periodic-ci-openshift-online-rosa-gap-analysis-main-nightly}"

# Get latest job executions for a given job name from job-history page
# Args: $1 = job_name, $2 = limit (default: 10)
# Returns: JSON array of job executions
get_job_executions() {
    local job_name="${1:-${DEFAULT_JOB_NAME}}"
    local limit="${2:-10}"

    # Fetch job-history page and extract allBuilds JavaScript array
    local all_builds
    all_builds=$(curl -s "${PROW_URL}/job-history/gs/test-platform-results/logs/${job_name}" | \
        grep -oP 'var allBuilds = \K\[.*?\];' | sed 's/;$//')

    if [ -z "${all_builds}" ]; then
        echo '{"items":[]}'
        return 1
    fi

    # Parse and limit results
    # Map Result values: "FAILURE", "SUCCESS", "PENDING", "ABORTED", "ERROR" -> lowercase for consistency
    echo "${all_builds}" | jq "{items: [.[] | {id: .ID, job_status: (.Result | ascii_downcase), start_time: .Started, duration: .Duration, spyglass_link: .SpyglassLink}] | .[0:${limit}]}"
}

# Get job execution details by ID
# Args: $1 = job_id (build_id), $2 = job_name (optional, for efficiency)
# Returns: JSON object with job execution details
get_job_execution() {
    local job_id="$1"
    local job_name="${2:-${DEFAULT_JOB_NAME}}"

    # Fetch job-history page and extract allBuilds JavaScript array
    local all_builds
    all_builds=$(curl -s "${PROW_URL}/job-history/gs/test-platform-results/logs/${job_name}" | \
        grep -oP 'var allBuilds = \K\[.*?\];' | sed 's/;$//')

    if [ -z "${all_builds}" ]; then
        echo '{"id":null,"job_status":null,"start_time":null,"completion_time":null,"duration":null}'
        return 1
    fi

    # Find job with matching ID
    echo "${all_builds}" | jq --arg id "${job_id}" '
        [.[] | select(.ID == $id)][0]
        | {
            id: .ID,
            job_status: (.Result | ascii_downcase),
            start_time: .Started,
            completion_time: null,
            duration: .Duration,
            spyglass_link: .SpyglassLink
        }
    '
}

# Find latest failed job
# Args: $1 = job_name (optional)
# Returns: Job ID of latest failed job
find_latest_failed_job() {
    local job_name="${1:-${DEFAULT_JOB_NAME}}"
    local limit="${2:-5}"
    local executions

    executions=$(get_job_executions "${job_name}" "${limit}")

    if [ -z "${executions}" ] || [ "${executions}" = "null" ]; then
        echo "ERROR: Failed to fetch job executions" >&2
        return 1
    fi

    # Find first job with failure status
    local failed_job_id
    failed_job_id=$(echo "${executions}" | jq -r '
        .items[]
        | select(.job_status == "failure" or .job_status == "error")
        | .id
        | select(. != null)
    ' | head -1)

    if [ -z "${failed_job_id}" ] || [ "${failed_job_id}" = "null" ]; then
        echo "ERROR: No failed jobs found for ${job_name}" >&2
        return 1
    fi

    echo "${failed_job_id}"
}

# Get artifact URLs for a job
# Args: $1 = job_name, $2 = job_id
# Returns: JSON object with artifact URLs
get_artifact_urls() {
    local job_name="$1"
    local job_id="$2"

    # GCS path structure: logs/{job_name}/{job_id}/artifacts/test/artifacts/rosa-gap-analysis-reports/
    local gcs_path="${job_name}/${job_id}/artifacts/test/artifacts/rosa-gap-analysis-reports"
    local base_url="${GCS_BASE_URL}/${gcs_path}"

    cat <<EOF
{
  "gcs_path": "${gcs_path}",
  "base_url": "${base_url}",
  "build_log": "https://storage.googleapis.com/test-platform-results/logs/${job_name}/${job_id}/build-log.txt",
  "artifacts_dir": "${base_url}"
}
EOF
}

# Download entire job directory using gcloud storage
# Args: $1 = job_name, $2 = job_id, $3 = output_dir
# Returns: 0 on success, 1 on failure
download_job_directory_gcs() {
    local job_name="$1"
    local job_id="$2"
    local output_dir="$3"

    # GCS path for entire job
    local gcs_path="gs://test-platform-results/logs/${job_name}/${job_id}/"

    # Download entire job directory
    if ! gcloud storage cp -r "${gcs_path}" "${output_dir}/" 2>&1; then
        echo "ERROR: Failed to download job directory from ${gcs_path}" >&2
        return 1
    fi

    return 0
}

# Find gap-analysis report files in downloaded directory
# Args: $1 = job_dir (local path to job directory)
# Returns: List of report file paths
find_gap_analysis_reports() {
    local job_dir="$1"

    # Find gap-analysis report files anywhere in the directory tree
    local reports
    reports=$(find "${job_dir}" -type f \( -name "gap-analysis-*.json" -o -name "gap-analysis-*.html" -o -name "gap-analysis-*.md" \) 2>/dev/null || true)

    if [ -z "${reports}" ]; then
        # Also try to find any .json/.html/.md files in rosa-gap-analysis-reports directory
        reports=$(find "${job_dir}" -type f -path "*/rosa-gap-analysis-reports/*" \( -name "*.json" -o -name "*.html" -o -name "*.md" \) 2>/dev/null || true)
    fi

    if [ -z "${reports}" ]; then
        echo "ERROR: No gap-analysis report files found in ${job_dir}" >&2
        echo "ERROR: Searched for: gap-analysis-*.{json,html,md} files" >&2
        echo "ERROR: Also searched: */rosa-gap-analysis-reports/* files" >&2

        # Debug: show what directories exist
        echo "DEBUG: Directory structure:" >&2
        find "${job_dir}" -type d 2>/dev/null | head -20 >&2

        return 1
    fi

    echo "${reports}"
}

# Get job metadata (versions, timestamps)
# Args: $1 = job_id
# Returns: JSON object with metadata
get_job_metadata() {
    local job_id="$1"
    local job_details

    job_details=$(get_job_execution "${job_id}")

    if [ -z "${job_details}" ] || [ "${job_details}" = "null" ]; then
        echo "ERROR: Failed to fetch job details" >&2
        return 1
    fi

    echo "${job_details}" | jq '{
        id: .id,
        status: .job_status,
        started: .start_time,
        finished: .completion_time,
        duration: .duration
    }'
}
