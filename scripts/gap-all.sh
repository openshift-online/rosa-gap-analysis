#!/bin/bash
# Run all gap analyses
# Orchestrates execution of all individual gap analysis scripts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# Always use project root
PROJECT_ROOT="$(get_project_root)"

BASELINE=""
TARGET=""
VERBOSE=false

usage() {
    cat <<EOF
Usage: $0 --baseline <version> --target <version> [OPTIONS]

Run gap analysis between two OpenShift versions for both AWS and GCP platforms.
Exits with code 0 if no policy differences found, non-zero if differences exist.

Required Arguments:
  --baseline <version>     Baseline version (e.g., 4.21)
  --target <version>       Target version (e.g., 4.22)

Optional Arguments:
  --verbose                Enable verbose logging
  -h, --help               Show this help

Examples:
  # Run analysis for both AWS STS and GCP WIF
  $0 --baseline 4.21 --target 4.22

  # With verbose logging
  $0 --baseline 4.21 --target 4.22 --verbose

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

if [[ -z "$BASELINE" ]] || [[ -z "$TARGET" ]]; then
    log_error "Missing required arguments"
    usage
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
