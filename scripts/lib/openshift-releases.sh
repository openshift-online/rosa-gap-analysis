#!/bin/bash
# OpenShift Release Information Library
# Functions to query OpenShift release data from Sippy and OCP releases

# Source logging utilities if available
_OPENSHIFT_RELEASES_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${_OPENSHIFT_RELEASES_SCRIPT_DIR}/logging.sh" ]]; then
    source "${_OPENSHIFT_RELEASES_SCRIPT_DIR}/logging.sh"
fi

# API endpoints
readonly SIPPY_API="https://sippy.dptools.openshift.org/api/releases"
readonly ACCEPTED_STREAMS_API="https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted"
# RELEASE_STREAM_BASE still needed for pullspec/nightly functions (accepted API doesn't provide pullspecs)
readonly RELEASE_STREAM_BASE="https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream"
readonly STABLE_STREAM="4-stable"
readonly DEV_PREVIEW_STREAM="4-dev-preview"

# Cache for accepted streams (to avoid multiple API calls)
_ACCEPTED_STREAMS_CACHE=""

# Helper function to extract minor version number from version string
# Usage: extract_minor_version "4.21"
# Returns: Minor version number (e.g., "21")
extract_minor_version() {
    local version="$1"
    echo "$version" | cut -d'.' -f2
}

# Helper function to extract base version from candidate version string
# Usage: extract_version_from_candidate "4.22.0-ec.3"
# Returns: Base version (e.g., "4.22")
extract_version_from_candidate() {
    local candidate="$1"
    # Extract major.minor from candidate version (e.g., "4.22.0-ec.3" -> "4.22")
    echo "$candidate" | sed -E 's/^([0-9]+\.[0-9]+)\..*/\1/'
}

# Helper function to extract base version from stable version string
# Usage: extract_version_from_stable "4.21.6"
# Returns: Base version (e.g., "4.21")
extract_version_from_stable() {
    local stable="$1"
    # Extract major.minor from stable version (e.g., "4.21.6" -> "4.21")
    echo "$stable" | sed -E 's/^([0-9]+\.[0-9]+)\..*/\1/'
}

# Validate that candidate version belongs to the expected version
# Usage: validate_candidate_belongs_to_version <candidate> <expected_version>
# Arguments:
#   $1 - Candidate version (e.g., "4.22.0-ec.3")
#   $2 - Expected version (e.g., "4.22")
# Returns: 0 if valid (candidate belongs to expected version), 1 otherwise
validate_candidate_belongs_to_version() {
    local candidate="$1"
    local expected_version="$2"

    if [[ -z "$candidate" ]] || [[ -z "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Both candidate and expected version required for validation"
        else
            echo "Error: Both candidate and expected version required for validation" >&2
        fi
        return 1
    fi

    local candidate_base=$(extract_version_from_candidate "$candidate")

    if [[ "$candidate_base" != "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Candidate version ($candidate) does not belong to expected version ($expected_version), found $candidate_base instead"
        else
            echo "Error: Candidate version ($candidate) does not belong to expected version ($expected_version)" >&2
        fi
        return 1
    fi

    return 0
}

# Validate that stable version belongs to the expected version
# Usage: validate_stable_belongs_to_version <stable> <expected_version>
# Arguments:
#   $1 - Stable version (e.g., "4.21.6")
#   $2 - Expected version (e.g., "4.21")
# Returns: 0 if valid (stable belongs to expected version), 1 otherwise
validate_stable_belongs_to_version() {
    local stable="$1"
    local expected_version="$2"

    if [[ -z "$stable" ]] || [[ -z "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Both stable and expected version required for validation"
        else
            echo "Error: Both stable and expected version required for validation" >&2
        fi
        return 1
    fi

    local stable_base=$(extract_version_from_stable "$stable")

    if [[ "$stable_base" != "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Stable version ($stable) does not belong to expected version ($expected_version), found $stable_base instead"
        else
            echo "Error: Stable version ($stable) does not belong to expected version ($expected_version)" >&2
        fi
        return 1
    fi

    return 0
}

# Get the latest GA (generally available) OpenShift version
# Usage: get_latest_ga_version
# Returns: Version string (e.g., "4.21") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_ga_version() {
    local version

    version=$(curl -s --fail "${SIPPY_API}" 2>/dev/null | \
        jq -r '.ga_dates | keys | sort_by(split(".") | map(tonumber)) | last' 2>/dev/null)

    if [[ -z "$version" ]] || [[ "$version" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest GA version from Sippy API"
        else
            echo "Error: Failed to fetch latest GA version" >&2
        fi
        return 1
    fi

    echo "$version"
    return 0
}

# Fetch all accepted release streams (cached to avoid multiple API calls)
# Usage: fetch_accepted_streams
# Returns: JSON object with accepted streams: {"4-stable": [...], "4-dev-preview": [...]}
# Exit: 0 on success, 1 on failure
fetch_accepted_streams() {
    # Return cached value if available
    if [[ -n "$_ACCEPTED_STREAMS_CACHE" ]]; then
        echo "$_ACCEPTED_STREAMS_CACHE"
        return 0
    fi

    # Fetch and cache the accepted streams
    _ACCEPTED_STREAMS_CACHE=$(curl -s --fail "$ACCEPTED_STREAMS_API" 2>/dev/null)

    if [[ -z "$_ACCEPTED_STREAMS_CACHE" ]] || [[ "$_ACCEPTED_STREAMS_CACHE" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch accepted release streams"
        else
            echo "Error: Failed to fetch accepted release streams" >&2
        fi
        return 1
    fi

    echo "$_ACCEPTED_STREAMS_CACHE"
    return 0
}

# Get the latest development version (not yet GA)
# Ensures dev version is exactly 1 minor version ahead of GA
# Usage: get_latest_dev_version
# Returns: Version string (e.g., "4.22") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_dev_version() {
    local ga_version
    local ga_minor
    local expected_dev_minor
    local expected_dev_version
    local all_releases

    # Get latest GA version first
    ga_version=$(get_latest_ga_version) || return 1

    # Calculate expected dev version (GA + 1)
    ga_minor=$(extract_minor_version "$ga_version")
    expected_dev_minor=$((ga_minor + 1))
    expected_dev_version="4.${expected_dev_minor}"

    # Get all available releases
    all_releases=$(curl -s --fail "${SIPPY_API}" 2>/dev/null | \
        jq -r '.releases[]' 2>/dev/null)

    if [[ -z "$all_releases" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch releases from Sippy API"
        else
            echo "Error: Failed to fetch releases from Sippy API" >&2
        fi
        return 1
    fi

    # Check if expected dev version exists in releases
    if echo "$all_releases" | grep -q "^${expected_dev_version}$"; then
        echo "$expected_dev_version"
        return 0
    else
        if command -v log_error &>/dev/null; then
            log_error "Expected dev version ${expected_dev_version} (GA+1) not found in available releases"
        else
            echo "Error: Expected dev version ${expected_dev_version} (GA+1) not found in available releases" >&2
        fi
        return 1
    fi
}

# Get the latest candidate (RC or EC) version for GA+1 from accepted streams
# First checks 4-stable for RC version, falls back to 4-dev-preview for EC version
# Usage: get_latest_candidate_version
# Returns: Latest candidate version (e.g., "4.22.0-rc.0" or "4.22.0-ec.5") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_candidate_version() {
    local ga_version
    local dev_version
    local streams
    local latest_candidate

    # Get GA version first
    ga_version=$(get_latest_ga_version) || return 1

    # Calculate dev version (GA + 1)
    local ga_minor
    ga_minor=$(echo "$ga_version" | cut -d. -f2)
    local dev_minor=$((ga_minor + 1))
    dev_version="4.${dev_minor}"

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Priority 1: Check 4-stable for RC version (e.g., 4.22.0-rc.*)
    # Versions are already sorted newest first
    latest_candidate=$(echo "$streams" | \
        jq -r --arg stream "$STABLE_STREAM" --arg dev "$dev_version" '.[$stream][] | select(startswith($dev + ".0-rc."))' 2>/dev/null | head -1)

    if [[ -n "$latest_candidate" ]] && [[ "$latest_candidate" != "null" ]]; then
        if command -v log_info &>/dev/null; then
            log_info "Found RC version in ${STABLE_STREAM}: $latest_candidate"
        fi
        echo "$latest_candidate"
        return 0
    fi

    # Priority 2: No RC in stable, check 4-dev-preview for EC version (e.g., 4.22.0-ec.*)
    latest_candidate=$(echo "$streams" | \
        jq -r --arg stream "$DEV_PREVIEW_STREAM" --arg dev "$dev_version" '.[$stream][] | select(startswith($dev + ".0-ec."))' 2>/dev/null | head -1)

    if [[ -z "$latest_candidate" ]] || [[ "$latest_candidate" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch candidate version for ${dev_version}.x (no RC in ${STABLE_STREAM}, no EC in ${DEV_PREVIEW_STREAM})"
        else
            echo "Error: Failed to fetch candidate version for ${dev_version}.x" >&2
        fi
        return 1
    fi

    if command -v log_info &>/dev/null; then
        log_info "Found EC version in ${DEV_PREVIEW_STREAM}: $latest_candidate"
    fi

    echo "$latest_candidate"
    return 0
}

# Get the latest stable version from accepted streams
# Ensures stable version belongs to GA version
# Usage: get_latest_stable_version
# Returns: Latest stable version (e.g., "4.21.11") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_stable_version() {
    local ga_version
    local streams
    local latest_stable

    # Get GA version first (e.g., "4.21")
    ga_version=$(get_latest_ga_version) || return 1

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Extract 4-stable array and filter by GA version line (e.g., 4.21.x)
    # Versions are already sorted newest first in the accepted API
    latest_stable=$(echo "$streams" | \
        jq -r --arg stream "$STABLE_STREAM" --arg ga "$ga_version" '.[$stream][] | select(startswith($ga + "."))' 2>/dev/null | head -1)

    if [[ -z "$latest_stable" ]] || [[ "$latest_stable" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest stable version for ${ga_version}.x from ${STABLE_STREAM} accepted stream"
        else
            echo "Error: Failed to fetch latest stable version for ${ga_version}.x from ${STABLE_STREAM} accepted stream" >&2
        fi
        return 1
    fi

    # Validate that stable belongs to GA version (should always pass now due to filter)
    if ! validate_stable_belongs_to_version "$latest_stable" "$ga_version"; then
        return 1
    fi

    echo "$latest_stable"
    return 0
}

# Get the latest stable version pullspec from stable stream
# Ensures stable version belongs to GA version
# Usage: get_latest_stable_pullspec
# Returns: Pullspec for latest stable version (e.g., "quay.io/openshift-release-dev/ocp-release:4.21.6-x86_64")
# Exit: 0 on success, 1 on failure
get_latest_stable_pullspec() {
    local api_url
    local ga_version
    local stable_version
    local pullspec

    # Get GA version first (e.g., "4.21")
    ga_version=$(get_latest_ga_version) || return 1

    # Build API URL for stable stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${STABLE_STREAM}/tags"

    # Fetch tags and filter to only those matching GA version line (e.g., 4.21.x)
    # Get both name and pullspec for the first matching tag
    local result
    result=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r --arg ga "$ga_version" '.tags[] | select(.name | startswith($ga + ".")) | {name: .name, pullSpec: .pullSpec} | @json' 2>/dev/null | head -1)

    if [[ -z "$result" ]] || [[ "$result" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest stable version for ${ga_version}.x from ${STABLE_STREAM} stream"
        else
            echo "Error: Failed to fetch latest stable version for ${ga_version}.x from ${STABLE_STREAM} stream" >&2
        fi
        return 1
    fi

    stable_version=$(echo "$result" | jq -r '.name')
    pullspec=$(echo "$result" | jq -r '.pullSpec')

    # Validate that stable belongs to GA version (should always pass now due to filter)
    if ! validate_stable_belongs_to_version "$stable_version" "$ga_version"; then
        return 1
    fi

    if [[ -z "$pullspec" ]] || [[ "$pullspec" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch pullspec for stable version ${stable_version}"
        else
            echo "Error: Failed to fetch pullspec for stable version ${stable_version}" >&2
        fi
        return 1
    fi

    echo "$pullspec"
    return 0
}

# Get the latest candidate (RC or EC) version pullspec
# First checks 4-stable for RC, falls back to 4-dev-preview for EC
# Usage: get_latest_candidate_pullspec
# Returns: Pullspec for latest candidate version (e.g., "quay.io/openshift-release-dev/ocp-release:4.22.0-rc.1-x86_64" or "registry.ci.openshift.org/ocp/release:4.22.0-ec.3")
# Exit: 0 on success, 1 on failure
get_latest_candidate_pullspec() {
    local ga_version
    local dev_version
    local candidate_version
    local pullspec
    local stable_api_url
    local dev_api_url

    # Get GA version first
    ga_version=$(get_latest_ga_version) || return 1

    # Calculate dev version (GA + 1)
    local ga_minor
    ga_minor=$(echo "$ga_version" | cut -d. -f2)
    local dev_minor=$((ga_minor + 1))
    dev_version="4.${dev_minor}"

    # Step 1: Check 4-stable stream for RC version
    stable_api_url="${RELEASE_STREAM_BASE}/${STABLE_STREAM}/tags"

    # Get candidate version and pullspec from stable stream
    local stable_result
    stable_result=$(curl -s --fail "$stable_api_url" 2>/dev/null | \
        jq -r --arg dev "$dev_version" '.tags[] | select(.name | startswith($dev + ".0-rc.")) | {name: .name, pullSpec: .pullSpec} | @json' 2>/dev/null | head -1)

    if [[ -n "$stable_result" ]] && [[ "$stable_result" != "null" ]]; then
        candidate_version=$(echo "$stable_result" | jq -r '.name')
        pullspec=$(echo "$stable_result" | jq -r '.pullSpec')

        if [[ -n "$pullspec" ]] && [[ "$pullspec" != "null" ]]; then
            echo "$pullspec"
            return 0
        fi
    fi

    # Step 2: No RC in stable, check 4-dev-preview stream for EC version
    dev_api_url="${RELEASE_STREAM_BASE}/${DEV_PREVIEW_STREAM}/tags"

    # Get candidate version and pullspec from dev-preview stream
    local dev_result
    dev_result=$(curl -s --fail "$dev_api_url" 2>/dev/null | \
        jq -r --arg dev "$dev_version" '.tags[] | select(.name | startswith($dev + ".0-ec.")) | {name: .name, pullSpec: .pullSpec} | @json' 2>/dev/null | head -1)

    if [[ -z "$dev_result" ]] || [[ "$dev_result" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch candidate pullspec for ${dev_version}.x"
        else
            echo "Error: Failed to fetch candidate pullspec for ${dev_version}.x" >&2
        fi
        return 1
    fi

    candidate_version=$(echo "$dev_result" | jq -r '.name')
    pullspec=$(echo "$dev_result" | jq -r '.pullSpec')

    if [[ -z "$pullspec" ]] || [[ "$pullspec" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch pullspec for candidate version ${candidate_version}"
        else
            echo "Error: Failed to fetch pullspec for candidate version ${candidate_version}" >&2
        fi
        return 1
    fi

    echo "$pullspec"
    return 0
}

# Get the latest nightly build pull spec for a given version
# Usage: get_latest_nightly_pullspec <version>
# Arguments:
#   $1 - Version (e.g., "4.22")
# Returns: Pull spec (e.g., "registry.ci.openshift.org/ocp/release:4.22.0-0.nightly-2026-03-13-184504")
# Exit: 0 on success, 1 on failure
get_latest_nightly_pullspec() {
    local version="$1"
    local api_url
    local pullspec

    if [[ -z "$version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Version parameter required"
        else
            echo "Error: Version parameter required" >&2
        fi
        return 1
    fi

    # Build API URL (amd64)
    api_url="${RELEASE_STREAM_BASE}/${version}.0-0.nightly/latest?rel=1"

    pullspec=$(curl -s --fail "$api_url" 2>/dev/null | jq -r '.pullSpec' 2>/dev/null)

    if [[ -z "$pullspec" ]] || [[ "$pullspec" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch nightly pullspec for version ${version}"
        else
            echo "Error: Failed to fetch nightly pullspec for version ${version}" >&2
        fi
        return 1
    fi

    echo "$pullspec"
    return 0
}

# Get the latest nightly version tag for dev version
# Usage: get_latest_dev_nightly_version
# Returns: Nightly version tag (e.g., "4.22.0-0.nightly-2026-03-13-184504")
# Exit: 0 on success, 1 on failure
get_latest_dev_nightly_version() {
    local dev_version
    local api_url
    local nightly_version

    # Get dev version first
    dev_version=$(get_latest_dev_version) || return 1

    # Build API URL for nightly stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${dev_version}.0-0.nightly/latest?rel=1"

    # Fetch nightly version tag
    nightly_version=$(curl -s --fail "$api_url" 2>/dev/null | jq -r '.name' 2>/dev/null)

    if [[ -z "$nightly_version" ]] || [[ "$nightly_version" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch nightly version for dev version ${dev_version}"
        else
            echo "Error: Failed to fetch nightly version for dev version ${dev_version}" >&2
        fi
        return 1
    fi

    echo "$nightly_version"
    return 0
}

# Get the latest nightly pullspec for dev version
# Usage: get_latest_dev_nightly_pullspec
# Returns: Nightly pullspec (e.g., "registry.ci.openshift.org/ocp/release:4.22.0-0.nightly-2026-03-13-184504")
# Exit: 0 on success, 1 on failure
get_latest_dev_nightly_pullspec() {
    local dev_version

    # Get dev version first
    dev_version=$(get_latest_dev_version) || return 1

    # Use existing function to get nightly pullspec
    get_latest_nightly_pullspec "$dev_version"
}

# Export functions for use in other scripts
export -f extract_minor_version
export -f extract_version_from_candidate
export -f extract_version_from_stable
export -f validate_candidate_belongs_to_version
export -f validate_stable_belongs_to_version
export -f get_latest_ga_version
export -f get_latest_dev_version
export -f get_latest_candidate_version
export -f get_latest_candidate_pullspec
export -f get_latest_stable_version
export -f get_latest_stable_pullspec
export -f get_latest_nightly_pullspec
export -f get_latest_dev_nightly_version
export -f get_latest_dev_nightly_pullspec

# If script is executed directly (not sourced), provide CLI interface
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
        --latest-ga)
            get_latest_ga_version
            ;;
        --latest-dev)
            get_latest_dev_version
            ;;
        --latest-stable)
            get_latest_stable_version
            ;;
        --latest-stable-pullspec)
            get_latest_stable_pullspec
            ;;
        --latest-candidate)
            get_latest_candidate_version
            ;;
        --latest-candidate-pullspec)
            get_latest_candidate_pullspec
            ;;
        --latest-nightly)
            get_latest_dev_nightly_version
            ;;
        --latest-nightly-pullspec)
            get_latest_dev_nightly_pullspec
            ;;
        --nightly)
            if [[ -z "${2:-}" ]]; then
                echo "Usage: $0 --nightly <version>" >&2
                exit 1
            fi
            get_latest_nightly_pullspec "${2}"
            ;;
        --help|-h|"")
            cat <<EOF
OpenShift Release Information Library

Usage: $0 <command> [options]

Commands:
  --latest-ga                      Get latest GA version
  --latest-dev                     Get latest development version (GA+1)
  --latest-stable                  Get latest stable version (for GA version)
  --latest-stable-pullspec         Get pullspec for latest stable version
  --latest-candidate               Get latest candidate version (for dev version)
  --latest-candidate-pullspec      Get pullspec for latest candidate version
  --latest-nightly                 Get latest nightly version (for dev version)
  --latest-nightly-pullspec        Get pullspec for latest nightly version (for dev version)
  --nightly <version>              Get latest nightly pullspec for specific version
  --help, -h                       Show this help

Examples:
  $0 --latest-ga                      # Output: 4.21 (from Sippy API)
  $0 --latest-dev                     # Output: 4.22 (always GA+1)
  $0 --latest-stable                  # Output: 4.21.11 (latest 4.21.x from 4-stable, filtered by GA)
  $0 --latest-stable-pullspec         # Output: quay.io/openshift-release-dev/ocp-release:4.21.11-x86_64
  $0 --latest-candidate               # Output: 4.22.0-rc.0 or 4.22.0-ec.5 (RC from 4-stable, or EC from 4-dev-preview)
  $0 --latest-candidate-pullspec      # Output: quay.io/.../4.22.0-rc.0-x86_64 or registry.ci.../4.22.0-ec.5
  $0 --latest-nightly                 # Output: 4.22.0-0.nightly-2026-03-13-184504 (dev version)
  $0 --latest-nightly-pullspec        # Output: registry.ci.openshift.org/ocp/release:4.22.0-0.nightly...
  $0 --nightly 4.22                   # Output: registry.ci.openshift.org/ocp/release:4.22...

Notes:
  - Dev version is always exactly 1 minor version ahead of GA (e.g., GA=4.21, Dev=4.22)
  - Stable versions are filtered from 4-stable stream for GA version line only (e.g., 4.21.x for GA 4.21)
  - Candidate versions: first checks 4-stable for RC (e.g., 4.22.0-rc.*), falls back to 4-dev-preview for EC (e.g., 4.22.0-ec.*)
  - All validation is performed automatically when fetching versions

Can also be sourced in other scripts:
  source $0
  ga_version=\$(get_latest_ga_version)
  dev_version=\$(get_latest_dev_version)
  stable=\$(get_latest_stable_version)
  stable_pullspec=\$(get_latest_stable_pullspec)
  candidate=\$(get_latest_candidate_version)
  candidate_pullspec=\$(get_latest_candidate_pullspec)
  nightly_version=\$(get_latest_dev_nightly_version)
  nightly_pullspec=\$(get_latest_dev_nightly_pullspec)
  nightly=\$(get_latest_nightly_pullspec "4.22")

Additional functions available when sourced:
  - get_latest_candidate_version
  - get_latest_dev_nightly_version
  - get_latest_dev_nightly_pullspec
  - validate_candidate_belongs_to_version
  - validate_stable_belongs_to_version
  - extract_minor_version
  - extract_version_from_candidate
  - extract_version_from_stable

EOF
            exit 0
            ;;
        *)
            echo "Error: Unknown command: ${1}" >&2
            echo "Run '$0 --help' for usage" >&2
            exit 1
            ;;
    esac
fi
