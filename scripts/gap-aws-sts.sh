#!/bin/bash
# AWS STS Policy Gap Analysis
# Compares STS policies between two OpenShift versions

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/openshift-releases.sh"

# Default values
VERBOSE=false

# Extract credential requests using oc adm release extract
# Usage: extract_credential_requests "4.21.0" "aws"
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

# Convert CredentialsRequest YAML files to consolidated IAM policy JSON
# Usage: convert_credential_requests_to_policy "/path/to/crs"
convert_credential_requests_to_policy() {
    local cr_dir="$1"

    # Initialize empty policy document
    local policy='{"Version": "2012-10-17", "Statement": []}'

    # Count YAML files
    local yaml_count=$(find "$cr_dir" -name "*.yaml" 2>/dev/null | wc -l)
    if [[ $yaml_count -eq 0 ]]; then
        log_warning "No YAML files found in $cr_dir"
        echo "$policy"
        return 0
    fi

    log_info "Processing $yaml_count credential request file(s)..."

    # Process each YAML file in the directory
    for yaml_file in "$cr_dir"/*.yaml; do
        if [[ ! -f "$yaml_file" ]]; then
            continue
        fi

        local basename=$(basename "$yaml_file")

        # Extract statementEntries from the CredentialsRequest and convert to IAM policy format
        # The credentialRequests use lowercase keys (action, effect, resource)
        # IAM policies use capitalized keys (Action, Effect, Resource)
        local statements
        if command -v yq &> /dev/null; then
            statements=$(yq eval '.spec.providerSpec.statementEntries // []' "$yaml_file" -o json 2>/dev/null)
        else
            # Use Python helper script if yq is not available
            statements=$("${SCRIPT_DIR}/lib/parse-credentials-request.py" --cloud=aws --file="$yaml_file" 2>/dev/null)
        fi

        if [[ -z "$statements" ]] || [[ "$statements" == "[]" ]] || [[ "$statements" == "null" ]]; then
            continue
        fi

        # Convert to IAM format (capitalize keys) and merge
        policy=$(echo "$policy" | jq --argjson new "$statements" '
            .Statement += ($new | map({
                Effect: (.effect // .Effect),
                Action: (.action // .Action),
                Resource: (.resource // .Resource // "*"),
                Condition: (.condition // .Condition // null)
            } | if .Condition == null then del(.Condition) else . end))
        ' 2>/dev/null)

        if [[ $? -eq 0 ]]; then
            local stmt_count=$(echo "$statements" | jq '. | length' 2>/dev/null)
            log_info "  ✓ Processed ${basename}: ${stmt_count} statement(s)"
        fi
    done

    # Deduplicate and sort statements
    policy=$(echo "$policy" | jq '.Statement |= unique_by({Effect, Action, Resource, Condition})' 2>/dev/null)

    local total_statements=$(echo "$policy" | jq '.Statement | length' 2>/dev/null)
    log_success "Converted to IAM policy: ${total_statements} unique statement(s)"

    echo "$policy"
    return 0
}

# Get STS policy for a specific version
# Usage: get_sts_policy "4.21.0"
# Uses oc adm release extract to extract credential requests from release payload
get_sts_policy() {
    local version="$1"

    log_info "Fetching AWS STS policy for version ${version}..."

    # Check for oc CLI
    if ! command -v oc &> /dev/null; then
        log_error "oc CLI not found. Please install OpenShift CLI."
        return 1
    fi

    log_info "Using 'oc adm release extract' to fetch credential requests..."

    local cr_dir
    if cr_dir=$(extract_credential_requests "$version" "aws"); then
        local policy
        if policy=$(convert_credential_requests_to_policy "$cr_dir"); then
            # Validate we got actual data
            local stmt_count=$(echo "$policy" | jq '.Statement | length' 2>/dev/null)
            if [[ $stmt_count -gt 0 ]]; then
                # Clean up temp directory
                rm -rf "$cr_dir"
                log_success "Successfully extracted STS policy"
                echo "$policy"
                return 0
            else
                log_error "No statements found in extracted credential requests"
                rm -rf "$cr_dir"
                return 1
            fi
        fi
        rm -rf "$cr_dir"
    fi

    log_error "Failed to extract credential requests"
    return 1
}

# Usage function
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Analyze AWS STS policy gaps between two OpenShift versions.
Exits with code 0 if no policy differences found, non-zero if differences exist.

Optional Arguments:
  --baseline <version>    Baseline version (default: auto-detect from latest stable)
  --target <version>      Target version (default: auto-detect from latest candidate)
  --verbose               Enable verbose logging
  -h, --help              Show this help message

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

Note: This script analyzes AWS STS policies only. Platform is always 'aws'.

EOF
    exit 1
}

# Parse arguments
BASELINE=""
TARGET=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline)
            BASELINE="$2"
            shift 2
            ;;
        --target)
            TARGET="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
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

# Main execution
main() {
    log_info "Starting AWS STS Policy Gap Analysis"
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
        log_info "Platform: aws (AWS STS)"
    fi

    # Create temporary directory for policy files
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT

    # Step 1: Fetch baseline STS policy
    log_info "Fetching baseline STS policy..."
    baseline_policy="${TEMP_DIR}/${BASELINE}-aws-sts.json"
    # Use pullspec if available, otherwise use version string
    baseline_ref="${BASELINE_PULLSPEC:-$BASELINE}"
    get_sts_policy "$baseline_ref" > "$baseline_policy"

    # Step 2: Fetch target STS policy
    log_info "Fetching target STS policy..."
    target_policy="${TEMP_DIR}/${TARGET}-aws-sts.json"
    # Use pullspec if available, otherwise use version string
    target_ref="${TARGET_PULLSPEC:-$TARGET}"
    get_sts_policy "$target_ref" > "$target_policy"

    # Step 3: Compare policies
    log_info "Comparing STS policies..."
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

# Run main function
main "$@"
