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
REPORT_DIR="${REPORT_DIR:-reports}"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Run gap analysis between two OpenShift versions for both AWS and GCP platforms.
Logs detected policy differences but always exits 0 on successful execution.

Optional Arguments:
  --baseline <version>     Baseline version (default: auto-detect from latest stable)
  --target <version>       Target version (default: auto-detect from latest candidate)
  --verbose                Enable verbose logging
  --report-dir <path>      Directory to store reports (default: reports/)
  -h, --help               Show this help

Environment Variables:
  BASE_VERSION            Override baseline version (lower precedence than --baseline)
  TARGET_VERSION          Override target version (lower precedence than --target)
                          Special values: NIGHTLY (dev nightly), CANDIDATE (dev candidate)
  REPORT_DIR              Directory to store reports (default: reports/)

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
  0 - Successful execution (regardless of whether differences were found)
  1 - Execution failure (e.g., missing tools, network errors, invalid versions)

EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline) BASELINE="$2"; shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --verbose) VERBOSE=true; shift ;;
        --report-dir) REPORT_DIR="$2"; shift 2 ;;
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
    # Create report directory if it doesn't exist
    mkdir -p "$REPORT_DIR"

    log_info "========================================="
    log_info "  OpenShift Gap Analysis Suite"
    log_info "========================================="
    log_info "Baseline: $BASELINE"
    log_info "Target:   $TARGET"
    log_info "Platforms: AWS STS, GCP WIF, Feature Gates"
    log_info "Report Directory: $REPORT_DIR"
    log_info "========================================="

    local aws_result=0
    local gcp_result=0
    local feature_gates_result=0
    local aws_output=""
    local gcp_output=""
    local feature_gates_output=""

    # Set environment variable to skip individual reports (full report will be generated instead)
    export GAP_FULL_REPORT=1

    # Run AWS STS analysis
    log_info ""
    log_info "Running AWS STS Policy Gap Analysis..."
    aws_output=$(python3 "${SCRIPT_DIR}/gap-aws-sts.py" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        --report-dir "$REPORT_DIR" \
        $VERBOSE_FLAG 2>&1) || {
        log_error "AWS STS analysis failed to execute"
        exit 1
    }
    echo "$aws_output" >&2
    if echo "$aws_output" | grep -q "Policy differences detected"; then
        aws_result=1
    fi

    # Run GCP WIF analysis
    log_info ""
    log_info "Running GCP WIF Policy Gap Analysis..."
    gcp_output=$(python3 "${SCRIPT_DIR}/gap-gcp-wif.py" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        --report-dir "$REPORT_DIR" \
        $VERBOSE_FLAG 2>&1) || {
        log_error "GCP WIF analysis failed to execute"
        exit 1
    }
    echo "$gcp_output" >&2
    if echo "$gcp_output" | grep -q "Policy differences detected"; then
        gcp_result=1
    fi

    # Run Feature Gates analysis
    log_info ""
    log_info "Running Feature Gates Gap Analysis..."
    feature_gates_output=$(python3 "${SCRIPT_DIR}/gap-feature-gates.py" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        --report-dir "$REPORT_DIR" \
        $VERBOSE_FLAG 2>&1) || {
        log_error "Feature Gates analysis failed to execute"
        exit 1
    }
    echo "$feature_gates_output" >&2
    if echo "$feature_gates_output" | grep -q "Feature gate differences detected"; then
        feature_gates_result=1
    fi

    # Print summary
    log_info ""
    log_info "========================================="
    log_info "  Gap Analysis Complete!"
    log_info "========================================="

    if [[ $aws_result -eq 0 ]] && [[ $gcp_result -eq 0 ]] && [[ $feature_gates_result -eq 0 ]]; then
        log_success "No policy or feature gate differences found"
    else
        if [[ $aws_result -eq 1 ]]; then
            log_info "AWS STS: Policy differences detected"
        fi
        if [[ $gcp_result -eq 1 ]]; then
            log_info "GCP WIF: Policy differences detected"
        fi
        if [[ $feature_gates_result -eq 1 ]]; then
            log_info "Feature Gates: Differences detected"
        fi
        log_info "Differences detected - review recommended"
    fi

    # Generate combined report
    log_info ""
    log_info "Generating combined report..."
    python3 "${SCRIPT_DIR}/generate-combined-report.py" \
        --baseline "$BASELINE" \
        --target "$TARGET" \
        --report-dir "$REPORT_DIR" 2>&1 || {
        log_warning "Failed to generate combined report (individual reports still available)"
    }

    # Always exit 0 on successful completion
    exit 0
}

main "$@"
