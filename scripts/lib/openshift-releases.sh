#!/bin/bash
# OpenShift Release Information Library
# Functions to query OpenShift release data from Sippy and OCP releases

# Source common utilities if available
_OPENSHIFT_RELEASES_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${_OPENSHIFT_RELEASES_SCRIPT_DIR}/common.sh" ]]; then
    source "${_OPENSHIFT_RELEASES_SCRIPT_DIR}/common.sh"
fi

# API endpoints
readonly SIPPY_API="https://sippy.dptools.openshift.org/api/releases"
readonly RELEASE_STREAM_BASE="https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream"
readonly DEV_PREVIEW_STREAM="4-dev-preview"
readonly STABLE_STREAM="4-stable"

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

# Validate that dev version is exactly 1 minor version ahead of GA
# Usage: validate_version_gap <ga_version> <dev_version>
# Arguments:
#   $1 - GA version (e.g., "4.21")
#   $2 - Dev version (e.g., "4.22")
# Returns: 0 if valid (dev = ga + 1), 1 otherwise
validate_version_gap() {
    local ga_version="$1"
    local dev_version="$2"

    if [[ -z "$ga_version" ]] || [[ -z "$dev_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Both GA and dev versions required for validation"
        else
            echo "Error: Both GA and dev versions required for validation" >&2
        fi
        return 1
    fi

    local ga_minor=$(extract_minor_version "$ga_version")
    local dev_minor=$(extract_minor_version "$dev_version")
    local diff=$((dev_minor - ga_minor))

    if [[ $diff -eq 0 ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Dev version ($dev_version) is the same as GA version ($ga_version)"
        else
            echo "Error: Dev version ($dev_version) is the same as GA version ($ga_version)" >&2
        fi
        return 1
    elif [[ $diff -lt 0 ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Dev version ($dev_version) is older than GA version ($ga_version)"
        else
            echo "Error: Dev version ($dev_version) is older than GA version ($ga_version)" >&2
        fi
        return 1
    elif [[ $diff -gt 1 ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Dev version ($dev_version) is $diff versions ahead of GA ($ga_version), expected exactly 1"
        else
            echo "Error: Dev version ($dev_version) is $diff versions ahead of GA ($ga_version), expected exactly 1" >&2
        fi
        return 1
    fi

    return 0
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

# Get the latest candidate (RC) version from dev-preview stream
# Ensures candidate belongs to dev version (GA+1)
# Usage: get_latest_candidate_version
# Returns: Latest candidate version (e.g., "4.22.0-rc.1") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_candidate_version() {
    local api_url
    local dev_version
    local latest_candidate

    # Get dev version first to validate against
    dev_version=$(get_latest_dev_version) || return 1

    # Build API URL for dev-preview stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${DEV_PREVIEW_STREAM}/tags"

    # Fetch tags and get the latest one
    # Tags are returned in chronological order, so we take the first one (most recent)
    latest_candidate=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r '.tags[0].name' 2>/dev/null)

    if [[ -z "$latest_candidate" ]] || [[ "$latest_candidate" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest candidate version from ${DEV_PREVIEW_STREAM} stream"
        else
            echo "Error: Failed to fetch latest candidate version from ${DEV_PREVIEW_STREAM} stream" >&2
        fi
        return 1
    fi

    # Validate that candidate belongs to dev version
    if ! validate_candidate_belongs_to_version "$latest_candidate" "$dev_version"; then
        return 1
    fi

    echo "$latest_candidate"
    return 0
}

# Get all candidate versions from dev-preview stream
# Filters to only return candidates for dev version (GA+1)
# Usage: get_all_candidate_versions
# Returns: JSON array of candidate version names or empty on failure
# Exit: 0 on success, 1 on failure
get_all_candidate_versions() {
    local api_url
    local dev_version
    local all_tags
    local filtered_candidates

    # Get dev version first to filter candidates
    dev_version=$(get_latest_dev_version) || return 1

    # Build API URL for dev-preview stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${DEV_PREVIEW_STREAM}/tags"

    # Fetch all tag names
    all_tags=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r '[.tags[].name]' 2>/dev/null)

    if [[ -z "$all_tags" ]] || [[ "$all_tags" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch candidate versions from ${DEV_PREVIEW_STREAM} stream"
        else
            echo "Error: Failed to fetch candidate versions from ${DEV_PREVIEW_STREAM} stream" >&2
        fi
        return 1
    fi

    # Filter candidates to only include those for dev version
    # Example: if dev is "4.22", only include candidates starting with "4.22."
    filtered_candidates=$(echo "$all_tags" | jq -r --arg ver "$dev_version" \
        '[.[] | select(startswith($ver + "."))]')

    if [[ -z "$filtered_candidates" ]] || [[ "$filtered_candidates" == "[]" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "No candidate versions found for dev version ${dev_version} in ${DEV_PREVIEW_STREAM} stream"
        else
            echo "Error: No candidate versions found for dev version ${dev_version}" >&2
        fi
        return 1
    fi

    echo "$filtered_candidates"
    return 0
}

# Get the latest stable version from stable stream
# Ensures stable version belongs to GA version
# Usage: get_latest_stable_version
# Returns: Latest stable version (e.g., "4.21.6") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_stable_version() {
    local api_url
    local ga_version
    local latest_stable

    # Get GA version first to validate against
    ga_version=$(get_latest_ga_version) || return 1

    # Build API URL for stable stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${STABLE_STREAM}/tags"

    # Fetch tags and get the latest one
    # Tags are returned in chronological order, so we take the first one (most recent)
    latest_stable=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r '.tags[0].name' 2>/dev/null)

    if [[ -z "$latest_stable" ]] || [[ "$latest_stable" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest stable version from ${STABLE_STREAM} stream"
        else
            echo "Error: Failed to fetch latest stable version from ${STABLE_STREAM} stream" >&2
        fi
        return 1
    fi

    # Validate that stable belongs to GA version
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

    # Get GA version first to validate against
    ga_version=$(get_latest_ga_version) || return 1

    # Build API URL for stable stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${STABLE_STREAM}/tags"

    # Fetch tags and get the latest one's pullspec
    stable_version=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r '.tags[0].name' 2>/dev/null)

    if [[ -z "$stable_version" ]] || [[ "$stable_version" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest stable version from ${STABLE_STREAM} stream"
        else
            echo "Error: Failed to fetch latest stable version from ${STABLE_STREAM} stream" >&2
        fi
        return 1
    fi

    # Validate that stable belongs to GA version
    if ! validate_stable_belongs_to_version "$stable_version" "$ga_version"; then
        return 1
    fi

    # Get the pullspec
    pullspec=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r '.tags[0].pullSpec' 2>/dev/null)

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

# Get the latest candidate version pullspec from dev-preview stream
# Ensures candidate belongs to dev version (GA+1)
# Usage: get_latest_candidate_pullspec
# Returns: Pullspec for latest candidate version (e.g., "registry.ci.openshift.org/ocp/release:4.22.0-ec.3")
# Exit: 0 on success, 1 on failure
get_latest_candidate_pullspec() {
    local api_url
    local dev_version
    local candidate_version
    local pullspec

    # Get dev version first to validate against
    dev_version=$(get_latest_dev_version) || return 1

    # Build API URL for dev-preview stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${DEV_PREVIEW_STREAM}/tags"

    # Fetch tags and get the latest one's name
    candidate_version=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r '.tags[0].name' 2>/dev/null)

    if [[ -z "$candidate_version" ]] || [[ "$candidate_version" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest candidate version from ${DEV_PREVIEW_STREAM} stream"
        else
            echo "Error: Failed to fetch latest candidate version from ${DEV_PREVIEW_STREAM} stream" >&2
        fi
        return 1
    fi

    # Validate that candidate belongs to dev version
    if ! validate_candidate_belongs_to_version "$candidate_version" "$dev_version"; then
        return 1
    fi

    # Get the pullspec
    pullspec=$(curl -s --fail "$api_url" 2>/dev/null | \
        jq -r '.tags[0].pullSpec' 2>/dev/null)

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

# Get all GA versions
# Usage: get_all_ga_versions
# Returns: JSON array of GA versions
# Exit: 0 on success, 1 on failure
get_all_ga_versions() {
    local versions

    versions=$(curl -s --fail "${SIPPY_API}" 2>/dev/null | \
        jq -r '.ga_dates | keys | sort_by(split(".") | map(tonumber))' 2>/dev/null)

    if [[ -z "$versions" ]] || [[ "$versions" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch GA versions from Sippy API"
        else
            echo "Error: Failed to fetch GA versions" >&2
        fi
        return 1
    fi

    echo "$versions"
    return 0
}

# Check if a version is GA
# Usage: is_ga_version <version>
# Arguments:
#   $1 - Version to check (e.g., "4.21")
# Returns: 0 if GA, 1 if not GA or on error
is_ga_version() {
    local version="$1"
    local ga_versions

    if [[ -z "$version" ]]; then
        return 1
    fi

    ga_versions=$(get_all_ga_versions) || return 1

    echo "$ga_versions" | jq -e --arg v "$version" 'index($v) != null' &>/dev/null
    return $?
}

# Get nightly build for the latest GA version
# Usage: get_latest_ga_nightly
# Returns: Pull spec for latest GA version's nightly build
# Exit: 0 on success, 1 on failure
get_latest_ga_nightly() {
    local ga_version

    ga_version=$(get_latest_ga_version) || return 1
    get_latest_nightly_pullspec "$ga_version"
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
export -f validate_version_gap
export -f validate_candidate_belongs_to_version
export -f validate_stable_belongs_to_version
export -f get_latest_ga_version
export -f get_latest_dev_version
export -f get_latest_candidate_version
export -f get_latest_candidate_pullspec
export -f get_all_candidate_versions
export -f get_latest_stable_version
export -f get_latest_stable_pullspec
export -f get_latest_nightly_pullspec
export -f get_all_ga_versions
export -f is_ga_version
export -f get_latest_ga_nightly
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
  $0 --latest-ga                      # Output: 4.21
  $0 --latest-dev                     # Output: 4.22 (always GA+1)
  $0 --latest-stable                  # Output: 4.21.6 (latest stable for GA version)
  $0 --latest-stable-pullspec         # Output: quay.io/openshift-release-dev/ocp-release:4.21.6-x86_64
  $0 --latest-candidate               # Output: 4.22.0-ec.3 (latest candidate for dev version)
  $0 --latest-candidate-pullspec      # Output: registry.ci.openshift.org/ocp/release:4.22.0-ec.3
  $0 --latest-nightly                 # Output: 4.22.0-0.nightly-2026-03-13-184504 (dev version)
  $0 --latest-nightly-pullspec        # Output: registry.ci.openshift.org/ocp/release:4.22.0-0.nightly...
  $0 --nightly 4.22                   # Output: registry.ci.openshift.org/ocp/release:4.22...

Notes:
  - Dev version is always exactly 1 minor version ahead of GA (e.g., GA=4.21, Dev=4.22)
  - Stable versions always belong to the GA version (e.g., 4.21.6 for GA 4.21)
  - Candidate versions always belong to the dev version (e.g., 4.22.0-ec.3 for dev 4.22)
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
  - get_all_candidate_versions
  - get_all_ga_versions
  - is_ga_version
  - validate_version_gap
  - validate_candidate_belongs_to_version
  - validate_stable_belongs_to_version

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
