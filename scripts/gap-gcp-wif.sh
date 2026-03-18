#!/bin/bash
# GCP WIF Policy Gap Analysis
# Compares Workload Identity Federation policies between two OpenShift versions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

# Script directory and project root (calculate BEFORE sourcing libraries)
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/openshift-releases.sh"

# Always use project root
PROJECT_ROOT="$(get_project_root)"
VERBOSE=false

# Extract credential requests using oc adm release extract
# Usage: extract_credential_requests "4.21.0" "gcp"
# Cloud options: aws, sts, gcp, wif
extract_credential_requests() {
    local version="$1"
    local cloud="$2"

    # Create temp directory for credential requests
    local temp_dir=$(mktemp -d -t ocp-crs-XXXXXX)

    # Construct release image URL
    # Try parsing as a version number first
    local release_image
    if [[ "$version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?(-rc\.[0-9]+)?$ ]]; then
        release_image="quay.io/openshift-release-dev/ocp-release:${version}-x86_64"
    else
        # Assume it's already a full image reference
        release_image="$version"
    fi

    log_info "Extracting credential requests from ${release_image} for cloud=${cloud}"

    # Extract credential requests using oc adm release extract
    if ! oc adm release extract "$release_image" \
        --credentials-requests \
        --cloud="$cloud" \
        --to="$temp_dir" 2>&1 | grep -v "warning:" >&2; then
        log_error "Failed to extract credential requests for version ${version}"
        rm -rf "$temp_dir"
        return 1
    fi

    log_success "Credential requests extracted to: $temp_dir"
    echo "$temp_dir"
    return 0
}

# Convert GCP CredentialsRequest YAML files to consolidated policy JSON
# Usage: convert_credential_requests_to_policy "/path/to/crs"
convert_credential_requests_to_policy() {
    local cr_dir="$1"

    # Initialize empty policy document with GCP permissions list
    local policy='{"Version": "2012-10-17", "Statement": []}'

    # Count YAML files
    local yaml_count=$(find "$cr_dir" -name "*.yaml" 2>/dev/null | wc -l)
    if [[ $yaml_count -eq 0 ]]; then
        log_warning "No YAML files found in $cr_dir"
        echo "$policy"
        return 0
    fi

    log_info "Processing $yaml_count credential request file(s)..."

    # Collect all permissions from all files
    local all_permissions="[]"

    # Process each YAML file in the directory
    for yaml_file in "$cr_dir"/*.yaml; do
        if [[ ! -f "$yaml_file" ]]; then
            continue
        fi

        local basename=$(basename "$yaml_file")

        # Extract permissions from GCP CredentialsRequest
        # GCP format: spec.providerSpec.permissions (array of strings)
        local permissions
        if command -v yq &> /dev/null; then
            permissions=$(yq eval '.spec.providerSpec.permissions // []' "$yaml_file" -o json 2>/dev/null)
        else
            # Use Python helper script if yq is not available
            permissions=$("${SCRIPT_DIR}/lib/parse-credentials-request.py" --cloud=gcp --file="$yaml_file" 2>/dev/null)
        fi

        if [[ -z "$permissions" ]] || [[ "$permissions" == "[]" ]] || [[ "$permissions" == "null" ]]; then
            continue
        fi

        # Merge permissions into all_permissions array
        all_permissions=$(echo "$all_permissions" | jq --argjson new "$permissions" '. + $new' 2>/dev/null)

        if [[ $? -eq 0 ]]; then
            local perm_count=$(echo "$permissions" | jq '. | length' 2>/dev/null)
            log_info "  ✓ Processed ${basename}: ${perm_count} permission(s)"
        fi
    done

    # Convert GCP permissions to a policy-like format for comparison
    # Create a single statement with all permissions as Actions
    if [[ "$all_permissions" != "[]" ]]; then
        policy=$(echo "$all_permissions" | jq -s '
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": (.[0] | sort | unique),
                        "Resource": "*"
                    }
                ]
            }
        ' 2>/dev/null)
    fi

    local total_permissions=$(echo "$all_permissions" | jq '. | unique | length' 2>/dev/null)
    log_success "Converted to GCP IAM policy: ${total_permissions} unique permission(s)"

    echo "$policy"
    return 0
}

# Get WIF policy for a specific version
# Usage: get_wif_policy "4.21.0"
# Uses oc adm release extract to extract credential requests from release payload
get_wif_policy() {
    local version="$1"

    log_info "Fetching GCP WIF policy for version ${version}..."

    # Check for oc CLI
    if ! command -v oc &> /dev/null; then
        log_error "oc CLI not found. Please install OpenShift CLI."
        return 1
    fi

    log_info "Using 'oc adm release extract' to fetch credential requests..."

    local cr_dir=$(extract_credential_requests "$version" "gcp")

    if [[ -n "$cr_dir" ]] && [[ -d "$cr_dir" ]]; then
        log_info "Converting CredentialsRequests to GCP IAM policy..."
        local policy=$(convert_credential_requests_to_policy "$cr_dir")
        rm -rf "$cr_dir"

        if [[ -n "$policy" ]]; then
            local stmt_count=$(echo "$policy" | jq '.Statement | length' 2>/dev/null)
            if [[ $stmt_count -gt 0 ]]; then
                log_success "Successfully extracted WIF policy"
                echo "$policy"
                return 0
            else
                log_error "No statements found in extracted credential requests"
                return 1
            fi
        fi
    fi

    log_error "Failed to extract credential requests"
    return 1
}

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Analyze GCP WIF policy gaps between two OpenShift versions.
Exits with code 0 if no policy differences found, non-zero if differences exist.

Optional Arguments:
  --baseline <version>    Baseline version (default: auto-detect from latest stable)
  --target <version>      Target version (default: auto-detect from latest candidate)
  --verbose               Enable verbose logging
  -h, --help              Show this help

Environment Variables:
  BASE_VERSION           Override baseline version (lower precedence than --baseline)
  TARGET_VERSION         Override target version (lower precedence than --target)
                         Special values: NIGHTLY (dev nightly), CANDIDATE (dev candidate)

Version Resolution Precedence (highest to lowest):
  1. Command-line flags (--baseline, --target)
  2. Environment variables (BASE_VERSION, TARGET_VERSION)
  3. Auto-detected (latest stable for baseline, latest candidate for target)

Examples:
  # Auto-detect versions (stable → candidate)
  $0

  # Explicit versions via CLI
  $0 --baseline 4.21 --target 4.22
  $0 --baseline 4.21.6 --target 4.22.0-ec.3 --verbose

  # Using environment variables
  BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 $0

  # Use nightly as target
  TARGET_VERSION=NIGHTLY $0

  # Use candidate as target (explicit)
  TARGET_VERSION=CANDIDATE $0

Exit Codes:
  0 - No policy differences found
  1 - Policy differences detected

Note: This script analyzes GCP WIF policies only. Platform is always 'gcp'.

EOF
    exit 1
}

BASELINE=""
TARGET=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline) BASELINE="$2"; shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --verbose) VERBOSE=true; shift ;;
        -h|--help) usage ;;
        *) log_error "Unknown option: $1"; usage ;;
    esac
done

# Resolve baseline version with precedence: CLI > ENV > Auto-detect
BASELINE_PULLSPEC=""
if [[ -n "$BASELINE" ]]; then
    log_info "Using baseline version from CLI: $BASELINE"
elif [[ -n "${BASE_VERSION:-}" ]]; then
    BASELINE="$BASE_VERSION"
    log_info "Using baseline version from BASE_VERSION env: $BASELINE"
else
    log_info "Auto-detecting baseline version from latest stable..."
    BASELINE=$(get_latest_stable_version)
    BASELINE_PULLSPEC=$(get_latest_stable_pullspec)
    log_info "Auto-detected baseline version: $BASELINE"
    log_info "Auto-detected baseline pullspec: $BASELINE_PULLSPEC"
fi

# Resolve target version with precedence: CLI > ENV > Auto-detect
TARGET_PULLSPEC=""
if [[ -n "$TARGET" ]]; then
    log_info "Using target version from CLI: $TARGET"
elif [[ -n "${TARGET_VERSION:-}" ]]; then
    # Check if TARGET_VERSION is a special keyword
    if [[ "${TARGET_VERSION^^}" == "NIGHTLY" ]]; then
        log_info "TARGET_VERSION=NIGHTLY detected, using latest dev nightly..."
        TARGET=$(get_latest_dev_nightly_version)
        TARGET_PULLSPEC=$(get_latest_dev_nightly_pullspec)
        log_info "Auto-detected nightly target version: $TARGET"
        log_info "Auto-detected nightly target pullspec: $TARGET_PULLSPEC"
    elif [[ "${TARGET_VERSION^^}" == "CANDIDATE" ]]; then
        log_info "TARGET_VERSION=CANDIDATE detected, using latest candidate..."
        TARGET=$(get_latest_candidate_version)
        TARGET_PULLSPEC=$(get_latest_candidate_pullspec)
        log_info "Auto-detected candidate target version: $TARGET"
        log_info "Auto-detected candidate target pullspec: $TARGET_PULLSPEC"
    else
        TARGET="$TARGET_VERSION"
        log_info "Using target version from TARGET_VERSION env: $TARGET"
    fi
else
    log_info "Auto-detecting target version from latest candidate..."
    TARGET=$(get_latest_candidate_version)
    TARGET_PULLSPEC=$(get_latest_candidate_pullspec)
    log_info "Auto-detected target version: $TARGET"
    log_info "Auto-detected target pullspec: $TARGET_PULLSPEC"
fi

main() {
    log_info "Starting GCP WIF Policy Gap Analysis"
    log_info "========================================="
    log_info "Baseline version: $BASELINE"
    if [[ -n "$BASELINE_PULLSPEC" ]]; then
        log_info "Baseline pullspec: $BASELINE_PULLSPEC"
    fi
    log_info "Target version: $TARGET"
    if [[ -n "$TARGET_PULLSPEC" ]]; then
        log_info "Target pullspec: $TARGET_PULLSPEC"
    fi
    log_info "========================================="

    # Check prerequisites
    check_command jq
    check_command oc

    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Platform: gcp (GCP WIF)"
    fi

    # Create temporary directory for policy files
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT

    # Step 1: Fetch baseline WIF policy
    log_info "Fetching baseline WIF policy..."
    baseline_policy="${TEMP_DIR}/${BASELINE}-gcp-wif.json"
    # Use pullspec if available, otherwise use version string
    baseline_ref="${BASELINE_PULLSPEC:-$BASELINE}"
    get_wif_policy "$baseline_ref" > "$baseline_policy"

    # Step 2: Fetch target WIF policy
    log_info "Fetching target WIF policy..."
    target_policy="${TEMP_DIR}/${TARGET}-gcp-wif.json"
    # Use pullspec if available, otherwise use version string
    target_ref="${TARGET_PULLSPEC:-$TARGET}"
    get_wif_policy "$target_ref" > "$target_policy"

    # Step 3: Compare policies
    log_info "Comparing WIF policies..."
    comparison_file="${TEMP_DIR}/comparison.json"
    compare_sts_policies "$baseline_policy" "$target_policy" > "$comparison_file"

    # Step 4: Check for differences
    local added_count=$(jq '.actions.target_only | length' "$comparison_file")
    local removed_count=$(jq '.actions.baseline_only | length' "$comparison_file")
    local total_changes=$((added_count + removed_count))

    if [[ $total_changes -eq 0 ]]; then
        log_success "No policy differences found between $BASELINE and $TARGET"
        exit 0
    else
        log_warning "Policy differences detected: $added_count added, $removed_count removed"
        exit 1
    fi
}

main "$@"
