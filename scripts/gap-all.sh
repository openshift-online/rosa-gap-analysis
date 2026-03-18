#!/bin/bash
# Run all gap analyses
# Orchestrates execution of all individual gap analysis scripts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/openshift-releases.sh"

# Always use project root
PROJECT_ROOT="$(get_project_root)"

BASELINE=""
TARGET=""
VERBOSE=false

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Run gap analysis between two OpenShift versions for both AWS and GCP platforms.
Exits with code 0 if no policy differences found, non-zero if differences exist.

Optional Arguments:
  --baseline <version>     Baseline version (default: auto-detect from latest stable)
  --target <version>       Target version (default: auto-detect from latest candidate)
  --verbose                Enable verbose logging
  -h, --help               Show this help

Environment Variables:
  BASE_VERSION            Override baseline version (lower precedence than --baseline)
  TARGET_VERSION          Override target version (lower precedence than --target)
                          Special values: NIGHTLY (dev nightly), CANDIDATE (dev candidate)

Version Resolution Precedence (highest to lowest):
  1. Command-line flags (--baseline, --target)
  2. Environment variables (BASE_VERSION, TARGET_VERSION)
  3. Auto-detected (latest stable for baseline, latest candidate for target)

Examples:
  # Auto-detect versions (stable → candidate)
  $0

  # Run analysis for both AWS STS and GCP WIF with explicit versions
  $0 --baseline 4.21 --target 4.22

  # With verbose logging
  $0 --baseline 4.21.6 --target 4.22.0-ec.3 --verbose

  # Using environment variables
  BASE_VERSION=4.21.5 TARGET_VERSION=4.22.0-ec.2 $0

  # Use nightly as target
  TARGET_VERSION=NIGHTLY $0

  # Use candidate as target (explicit)
  TARGET_VERSION=CANDIDATE $0

Exit Codes:
  0 - No policy differences found in either platform
  1 - Policy differences detected in at least one platform

EOF
    exit 1
}

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

# Build verbose flag
VERBOSE_FLAG=""
if [[ "$VERBOSE" == "true" ]]; then
    VERBOSE_FLAG="--verbose"
fi

main() {
    log_info "========================================="
    log_info "  OpenShift Gap Analysis Suite"
    log_info "========================================="
    log_info "Baseline: $BASELINE"
    log_info "Target:   $TARGET"
    log_info "Platforms: AWS STS, GCP WIF"
    log_info "========================================="

    local aws_result=0
    local gcp_result=0

    # Run AWS STS analysis
    log_info ""
    log_info "Running AWS STS Policy Gap Analysis..."
    if bash "${SCRIPT_DIR}/gap-aws-sts.sh" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        $VERBOSE_FLAG; then
        log_success "No AWS STS policy differences found"
    else
        log_warning "AWS STS policy differences detected"
        aws_result=1
    fi

    # Run GCP WIF analysis
    log_info ""
    log_info "Running GCP WIF Policy Gap Analysis..."
    if bash "${SCRIPT_DIR}/gap-gcp-wif.sh" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        $VERBOSE_FLAG; then
        log_success "No GCP WIF policy differences found"
    else
        log_warning "GCP WIF policy differences detected"
        gcp_result=1
    fi

    # Print summary
    log_info ""
    log_info "========================================="
    log_info "  Gap Analysis Complete!"
    log_info "========================================="

    if [[ $aws_result -eq 0 ]] && [[ $gcp_result -eq 0 ]]; then
        log_success "No policy differences found in any platform"
        exit 0
    else
        if [[ $aws_result -eq 1 ]]; then
            log_warning "AWS STS: Policy differences detected"
        fi
        if [[ $gcp_result -eq 1 ]]; then
            log_warning "GCP WIF: Policy differences detected"
        fi
        log_warning "Policy differences detected - review required"
        exit 1
    fi
}

main "$@"
