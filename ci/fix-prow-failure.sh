#!/bin/bash

# =============================================================================
# Script: fix-prow-failure.sh
# Description: Fix Prow CI failures - generate files, validate, create PR
# Usage: ./ci/fix-prow-failure.sh [OPTIONS]
# =============================================================================

set -eo pipefail

# Colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default configuration
WORK_DIR="${GAP_WORK_DIR:-}"  # Use env var or require --work-dir
REPORT_FILE=""
AUTO_PR=false
DRY_RUN=false
SKIP_VALIDATION=false
CLEANUP_WORK_DIR=false  # Set to true if temp dir should be cleaned up

# Repository configuration (from config file or flags)
TARGET_REPO="${TARGET_REPO:-openshift/managed-cluster-config}"
TEST_REPO="${TEST_REPO:-}"
FORK_REPO="${FORK_REPO:-}"
USE_TEST_MODE=false

# PR configuration
REVIEWERS=""
LABELS="area/credentials"
GITHUB_USERNAME="${GITHUB_USERNAME:-}"  # Optional: validate gh auth username
GIT_USER_NAME="${GIT_USER_NAME:-Gap Analysis Bot}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-gap-bot@redhat.com}"

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

# Usage
usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Fix Prow CI validation failures by generating files, validating, and optionally creating PR.

This script:
  1. Generates fix files from gap-analysis failure report
  2. Validates generated files
  3. Optionally creates PR in target repository
     - Runs 'make' to generate additional required files
     - Checks for existing PRs to avoid duplicates

WORKFLOW:
    # Back-to-back workflow (recommended - uses temp directory)
    WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \\
      ./ci/fix-prow-failure.sh --work-dir "$WORK_DIR" --create-pr

    # Manual workflow (review reports first using persistent directory)
    ./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis
    ./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr

WORK DIRECTORY:
    --work-dir DIR        Work directory containing gap-analysis reports
                          (required: use --work-dir or set GAP_WORK_DIR env var)
    --report FILE         Path to gap-analysis JSON report
                          (default: latest in work directory)

GENERATION:
    --skip-validation     Skip validation after generation

PR CREATION:
    --create-pr           Create PR after validation succeeds
    --test-mode           Create PR to test repository (TEST_REPO)
    --test-repo REPO      Test repository (owner/repo, for --test-mode)
    --target-repo REPO    Target repository (owner/repo, for production)
    --fork-repo REPO      Fork repository (owner/repo, required for PR)
    --reviewers LIST      Comma-separated reviewers
    --labels LIST         Comma-separated labels (default: area/credentials)

OPTIONS:
    --dry-run             Preview changes without creating files/PR
    -h, --help            Display this help message

CONFIGURATION FILE:
    Edit ${PROJECT_ROOT}/.github-pr-config with your bot settings:

    TARGET_REPO="openshift/managed-cluster-config"  # Production upstream
    TEST_REPO="your-user/test-repo"                 # Test upstream
    FORK_REPO="bot-user/managed-cluster-config"     # Bot's fork
    REVIEWERS="reviewer1,reviewer2"
    LABELS="area/credentials"
    GITHUB_USERNAME="bot-user"        # Optional: validate gh auth user
    GIT_USER_NAME="Gap Analysis Bot"  # Bot identity for commits
    GIT_USER_EMAIL="gap-bot@redhat.com"

GITHUB AUTHENTICATION:
    Set GitHub Personal Access Token (PAT) as environment variable:
      export GH_TOKEN="ghp_yourPersonalAccessTokenHere"

    The script will automatically use this token for authentication.
    DO NOT commit the token to the repository.

    PAT Requirements:
      - Scopes: repo, read:org
      - User must have write access to FORK_REPO
      - User must be able to create PRs to TEST_REPO and TARGET_REPO

EXAMPLES:
    # Back-to-back workflow (analyze then fix)
    WORK_DIR=$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \\
      $(basename "$0") --work-dir "$WORK_DIR" --create-pr

    # Use persistent directory for review
    $(basename "$0") --work-dir ~/prow-analysis --create-pr

    # Generate and validate files only (legacy)
    $(basename "$0")

    # Generate, validate, and create test PR
    $(basename "$0") --work-dir /tmp/gap-work --create-pr --test-mode

    # Generate, validate, and create production PR
    $(basename "$0") --work-dir ~/prow-analysis --create-pr \\
      --reviewers "reviewer1,reviewer2"

    # Dry run
    $(basename "$0") --work-dir /tmp/gap-work --create-pr --dry-run

    # Override test repository
    $(basename "$0") --work-dir /tmp/gap-work --create-pr --test-mode \\
      --test-repo another-user/test-repo

PREREQUISITES:
    - gap-analysis failure report exists (run analyze-prow-failure.sh first)
    - python3, PyYAML, jq, yq installed
    - For PR creation: gh CLI authenticated, fork repository exists
    - Target repository should have a Makefile (for generating additional files)

NOTES:
    - Script runs 'make' in the repository to generate additional files
    - All files (manually generated + make-generated) are included in PR
    - Script checks for existing PRs before creating new ones
    - If PR already exists for the branch, returns existing PR URL
    - No duplicate PRs will be created

EOF
}

# Load configuration file
load_config() {
    local config_file="${PROJECT_ROOT}/.github-pr-config"
    if [ -f "${config_file}" ]; then
        log_info "Loading configuration from ${config_file}"
        # shellcheck source=/dev/null
        source "${config_file}"
    fi
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --work-dir)
                WORK_DIR="$2"
                shift 2
                ;;
            --report)
                REPORT_FILE="$2"
                shift 2
                ;;
            --create-pr)
                AUTO_PR=true
                shift
                ;;
            --test-mode)
                USE_TEST_MODE=true
                shift
                ;;
            --test-repo)
                TEST_REPO="$2"
                shift 2
                ;;
            --target-repo)
                TARGET_REPO="$2"
                shift 2
                ;;
            --fork-repo)
                FORK_REPO="$2"
                shift 2
                ;;
            --reviewers)
                REVIEWERS="$2"
                shift 2
                ;;
            --labels)
                LABELS="$2"
                shift 2
                ;;
            --skip-validation)
                SKIP_VALIDATION=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
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
}

# Find latest report if not specified
find_latest_report() {
    if [ -z "${REPORT_FILE}" ]; then
        REPORT_FILE=$(find "${WORK_DIR}" -name "gap-analysis-full_*.json" -type f -printf '%T@ %p\n' | sort -rn | head -1 | cut -d' ' -f2)

        if [ -z "${REPORT_FILE}" ]; then
            log_error "No gap-analysis report found in ${WORK_DIR}"
            log_error "Run analyze-prow-failure.sh first to download artifacts."
            exit 1
        fi

        log_info "Using latest report: $(basename "${REPORT_FILE}")"
    fi

    if [ ! -f "${REPORT_FILE}" ]; then
        log_error "Report file not found: ${REPORT_FILE}"
        exit 1
    fi
}

# Generate fix files
generate_fixes() {
    log_info "Generating fix files..."

    if [ "${DRY_RUN}" = true ]; then
        log_warn "[DRY RUN] Would generate files from: ${REPORT_FILE}"
        return 0
    fi

    # Call Python generation script
    if ! python3 "${SCRIPT_DIR}/lib/generate-fixes.py" \
        --report "${REPORT_FILE}" \
        --output-dir "${WORK_DIR}"; then
        log_error "Failed to generate fix files"
        exit 1
    fi

    log_success "✓ Fix files generated successfully"
}

# Validate generated files
validate_fixes() {
    log_info "Validating generated files..."

    local mcc_dir="${WORK_DIR}/managed-cluster-config"

    if [ "${DRY_RUN}" = true ]; then
        log_warn "[DRY RUN] Would validate files in: ${mcc_dir}"
        return 0
    fi

    if [ ! -d "${mcc_dir}" ]; then
        log_error "Generated files directory not found: ${mcc_dir}"
        exit 1
    fi

    local validation_failed=false

    # Check directory structure
    log_info "Checking directory structure..."
    local expected_dirs=("resources/sts" "resources/wif" "deploy/osd-cluster-acks/sts" "deploy/osd-cluster-acks/wif" "deploy/osd-cluster-acks/ocp")

    for dir in "${expected_dirs[@]}"; do
        if [ -d "${mcc_dir}/${dir}" ]; then
            log_success "✓ ${dir}"
        else
            log_warn "⚠ ${dir} - directory missing (may not be needed)"
        fi
    done

    # Validate AWS STS policy files (JSON)
    log_info "Validating AWS STS policy files..."
    local sts_count=0
    for policy_file in "${mcc_dir}"/resources/sts/*/openshift_*.json; do
        if [ -f "${policy_file}" ]; then
            if jq empty "${policy_file}" 2>/dev/null; then
                log_success "✓ $(basename "${policy_file}") - valid JSON"
                sts_count=$((sts_count + 1))
            else
                log_error "✗ $(basename "${policy_file}") - invalid JSON"
                validation_failed=true
            fi
        fi
    done

    if [ ${sts_count} -gt 0 ]; then
        log_success "Found ${sts_count} AWS STS policy files"
    fi

    # Validate GCP WIF template
    log_info "Validating GCP WIF template..."
    local wif_validation_script="${SCRIPT_DIR}/lib/validate-wif-template.sh"

    for wif_template in "${mcc_dir}"/resources/wif/*/vanilla.yaml; do
        if [ -f "${wif_template}" ]; then
            local wif_version=$(basename "$(dirname "${wif_template}")")

            # Check if yq is installed (required by validation script)
            if ! command -v yq &> /dev/null; then
                log_error "✗ yq is not installed - required for WIF template validation"
                log_error "  Install: https://github.com/mikefarah/yq"
                validation_failed=true
                continue
            fi

            # Check if validation script exists
            if [ ! -f "${wif_validation_script}" ]; then
                log_warn "⚠ WIF validation script not found at: ${wif_validation_script}"
                log_warn "  Skipping WIF template validation"
                continue
            fi

            # Run WIF validation
            log_info "Running WIF validation for ${wif_version}/vanilla.yaml..."
            local validation_output
            validation_output=$("${wif_validation_script}" "${wif_template}" 2>&1)
            local validation_exit_code=$?

            if [ ${validation_exit_code} -eq 0 ]; then
                log_success "✓ ${wif_version}/vanilla.yaml - passed WIF validation"
            else
                log_error "✗ ${wif_version}/vanilla.yaml - WIF validation failed:"
                echo "${validation_output}" | while IFS= read -r line; do
                    log_error "  ${line}"
                done
                validation_failed=true
            fi
        fi
    done

    # Validate acknowledgment files (YAML)
    log_info "Validating acknowledgment files..."
    local ack_count=0
    for ack_file in "${mcc_dir}"/deploy/osd-cluster-acks/*/*/*.yaml; do
        if [ -f "${ack_file}" ]; then
            if python3 -c "import yaml; yaml.safe_load(open('${ack_file}'))" 2>/dev/null; then
                log_success "✓ $(echo "${ack_file}" | sed "s|${mcc_dir}/||") - valid YAML"
                ack_count=$((ack_count + 1))
            else
                log_error "✗ $(echo "${ack_file}" | sed "s|${mcc_dir}/||") - invalid YAML"
                validation_failed=true
            fi
        fi
    done

    if [ ${ack_count} -gt 0 ]; then
        log_success "Found ${ack_count} acknowledgment files"
    fi

    if [ "${validation_failed}" = true ]; then
        log_error "Validation failed!"
        exit 1
    fi

    log_success "✓ All validations passed!"
}

# Validate GitHub prerequisites
validate_github_prerequisites() {
    local target_repo="$1"

    log_info "Validating GitHub prerequisites..."

    # Check gh CLI installed
    if ! command -v gh &> /dev/null; then
        log_error "gh CLI is not installed. Install from https://cli.github.com/"
        exit 1
    fi

    # Check for GH_TOKEN or GITHUB_TOKEN environment variable
    local token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
    if [ -z "${token}" ]; then
        log_error "GitHub Personal Access Token (PAT) required!"
        log_error ""
        log_error "Set your PAT as an environment variable:"
        log_error "  export GH_TOKEN=\"ghp_yourPersonalAccessTokenHere\""
        log_error ""
        log_error "Token requirements:"
        log_error "  - Scopes: repo, read:org"
        log_error "  - Username: ${GITHUB_USERNAME}"
        exit 1
    fi

    log_success "✓ GitHub token found in environment"

    # Get currently authenticated user (if any)
    local current_user=""
    if gh auth status &> /dev/null; then
        current_user=$(gh api user --jq '.login' 2>/dev/null || echo "")
    fi

    # Check if we need to switch users
    local needs_auth=false
    if [ -z "${current_user}" ]; then
        log_info "No active GitHub authentication, will authenticate as ${GITHUB_USERNAME}"
        needs_auth=true
    elif [ -n "${GITHUB_USERNAME}" ] && [ "${current_user}" != "${GITHUB_USERNAME}" ]; then
        log_warn "GitHub user mismatch: currently '${current_user}', need '${GITHUB_USERNAME}'"
        log_info "Switching to ${GITHUB_USERNAME}..."
        needs_auth=true
    fi

    # Authenticate if needed
    if [ "${needs_auth}" = true ]; then
        # Logout current user
        if [ -n "${current_user}" ]; then
            log_info "Logging out current user: ${current_user}"
            gh auth logout &> /dev/null || true
        fi

        # Login with token
        log_info "Authenticating as ${GITHUB_USERNAME} using PAT..."
        if ! echo "${token}" | gh auth login --with-token 2>/dev/null; then
            log_error "GitHub authentication failed!"
            log_error ""
            log_error "Please verify your GH_TOKEN:"
            log_error "  - Token is valid and not expired"
            log_error "  - Token has required scopes: repo, read:org"
            log_error "  - Token belongs to user: ${GITHUB_USERNAME}"
            log_error "  - Create token at: https://github.com/settings/tokens"
            exit 1
        fi

        # Configure git to use the token for HTTPS
        gh auth setup-git &> /dev/null || true

        log_success "✓ Authenticated as ${GITHUB_USERNAME}"
    else
        log_success "✓ Already authenticated as: ${current_user}"
    fi

    # Verify authentication
    local auth_user
    auth_user=$(gh api user --jq '.login' 2>/dev/null)

    if [ -z "${auth_user}" ]; then
        log_error "Failed to verify GitHub authentication"
        exit 1
    fi

    # Final validation against configured username
    if [ -n "${GITHUB_USERNAME}" ] && [ "${auth_user}" != "${GITHUB_USERNAME}" ]; then
        log_error "GitHub authentication verification failed!"
        log_error "  Expected: ${GITHUB_USERNAME}"
        log_error "  Actual: ${auth_user}"
        exit 1
    fi

    # Check fork repository exists and is accessible
    log_info "Checking fork repository: ${FORK_REPO}..."
    if ! gh repo view "${FORK_REPO}" &> /dev/null; then
        log_error "Cannot access fork repository: ${FORK_REPO}"
        log_error ""
        log_error "Possible issues:"
        log_error "  - Repository does not exist"
        log_error "  - User '${auth_user}' lacks read access"
        log_error "  - Repository name is incorrect"
        exit 1
    fi

    # Check fork permissions (can we push?)
    local fork_permissions
    fork_permissions=$(gh repo view "${FORK_REPO}" --json viewerPermission --jq '.viewerPermission' 2>/dev/null)

    if [[ "${fork_permissions}" != "ADMIN" ]] && [[ "${fork_permissions}" != "WRITE" ]]; then
        log_error "Insufficient permissions on fork repository: ${FORK_REPO}"
        log_error "  Current permission: ${fork_permissions}"
        log_error "  Required: WRITE or ADMIN"
        log_error ""
        log_error "User '${auth_user}' must have write access to push branches."
        exit 1
    fi

    log_success "✓ Fork repository accessible (permission: ${fork_permissions})"

    # Check target repository exists
    log_info "Checking target repository: ${target_repo}..."
    if ! gh repo view "${target_repo}" &> /dev/null; then
        log_error "Cannot access target repository: ${target_repo}"
        log_error ""
        log_error "Possible issues:"
        log_error "  - Repository does not exist"
        log_error "  - Repository is private and user '${auth_user}' lacks access"
        log_error "  - Repository name is incorrect"
        exit 1
    fi

    log_success "✓ Target repository accessible"
    log_success "✓ All GitHub prerequisites validated"
}

# Generate PR body from template
generate_pr_body() {
    local version="$1"
    local baseline="$2"
    local target="$3"
    local prow_job_url="$4"
    local html_report_url="$5"
    local ocp_has_gates="$6"

    local template_file="${SCRIPT_DIR}/templates/pr-body.md"
    local mcc_dir="${WORK_DIR}/managed-cluster-config"

    if [ ! -f "${template_file}" ]; then
        log_error "PR template not found: ${template_file}"
        exit 1
    fi

    # Create temp files for building the PR body
    local failure_summary_file=$(mktemp)
    local files_added_file=$(mktemp)
    trap "rm -f '${failure_summary_file}' '${files_added_file}'" RETURN

    # Count files by type (from generated files only - exclude make-generated)
    local aws_sts_count=0
    local gcp_wif_count=0
    local ack_count=0

    if [ -d "${mcc_dir}" ]; then
        aws_sts_count=$(find "${mcc_dir}/resources/sts" -type f -name "*.json" 2>/dev/null | wc -l)
        gcp_wif_count=$(find "${mcc_dir}/resources/wif" -type f -name "*.yaml" 2>/dev/null | wc -l)
        ack_count=$(find "${mcc_dir}/deploy/osd-cluster-acks" -type f \( -name "config.yaml" -o -name "*ack*.yaml" \) 2>/dev/null | wc -l)
    fi

    local total_files=$((aws_sts_count + gcp_wif_count + ack_count))

    # Extract AWS permission changes from JSON report
    local aws_added_permissions=""
    local aws_removed_permissions=""
    local ocp_has_gates="true"
    if [ -f "${REPORT_FILE}" ]; then
        # Get added permissions (target_only)
        aws_added_permissions=$(jq -r '.aws_sts.comparison.actions.target_only[]? // empty' "${REPORT_FILE}" 2>/dev/null | sort | paste -sd, -)
        # Get removed permissions (baseline_only)
        aws_removed_permissions=$(jq -r '.aws_sts.comparison.actions.baseline_only[]? // empty' "${REPORT_FILE}" 2>/dev/null | sort | paste -sd, -)

        # Check if OCP has admin gates requiring acknowledgment
        local gates_count=$(jq -r '.ocp_gate_ack.analysis.gates_requiring_ack | length' "${REPORT_FILE}" 2>/dev/null || echo "0")
        if [ "${gates_count}" -eq 0 ]; then
            ocp_has_gates="false"
        fi
    fi

    # Generate failure summary from JSON report
    if [ -f "${REPORT_FILE}" ]; then
        # Check AWS STS failures
        local aws_missing=$(jq -r '.aws_sts.validation.check1.status // "UNKNOWN"' "${REPORT_FILE}" 2>/dev/null)
        if [ "${aws_missing}" = "FAIL" ]; then
            echo "- **CHECK #1 (AWS STS):** Target directory resources/sts/${version}/ not found or empty" >> "${failure_summary_file}"
        fi

        local aws_ack_missing=$(jq -r '.aws_sts.validation.check2.status // "UNKNOWN"' "${REPORT_FILE}" 2>/dev/null)
        if [ "${aws_ack_missing}" = "FAIL" ]; then
            echo "- **CHECK #2 (AWS STS Acks):** Acknowledgment files missing in deploy/osd-cluster-acks/sts/${version}/" >> "${failure_summary_file}"
        fi

        # Check GCP WIF failures
        local gcp_missing=$(jq -r '.gcp_wif.validation.check3.status // "UNKNOWN"' "${REPORT_FILE}" 2>/dev/null)
        if [ "${gcp_missing}" = "FAIL" ]; then
            echo "- **CHECK #3 (GCP WIF):** vanilla.yaml not found in resources/wif/${version}/" >> "${failure_summary_file}"
        fi

        local gcp_ack_missing=$(jq -r '.gcp_wif.validation.check4.status // "UNKNOWN"' "${REPORT_FILE}" 2>/dev/null)
        if [ "${gcp_ack_missing}" = "FAIL" ]; then
            echo "- **CHECK #4 (GCP WIF Acks):** Acknowledgment files missing in deploy/osd-cluster-acks/wif/${version}/" >> "${failure_summary_file}"
        fi

        # Check OCP gate ack failures
        local ocp_ack_missing=$(jq -r '.ocp_gate_ack.validation.check5.status // "UNKNOWN"' "${REPORT_FILE}" 2>/dev/null)
        if [ "${ocp_ack_missing}" = "FAIL" ]; then
            echo "- **CHECK #5 (OCP Gate Acks):** Acknowledgment file missing in deploy/osd-cluster-acks/ocp/${version}/" >> "${failure_summary_file}"
        fi
    fi

    # If no specific failures found, use generic message
    if [ ! -s "${failure_summary_file}" ]; then
        echo "- Missing credential policies and acknowledgment files for OCP ${version}" > "${failure_summary_file}"
    fi

    # Generate files added list
    if [ -d "${mcc_dir}" ]; then
        # List AWS STS files with permission changes
        if [ ${aws_sts_count} -gt 0 ]; then
            echo "### AWS STS IAM Policies (${aws_sts_count})" >> "${files_added_file}"

            # Show per-file permission changes if available
            if [ -f "${REPORT_FILE}" ]; then
                local file_changes_count=$(jq -r '.aws_sts.comparison.file_changes | length' "${REPORT_FILE}" 2>/dev/null || echo "0")
                if [ "${file_changes_count}" -gt 0 ]; then
                    echo "" >> "${files_added_file}"
                    echo "**Permission Changes by File:**" >> "${files_added_file}"

                    # Iterate through file changes
                    jq -r '.aws_sts.comparison.file_changes[] | select(.actions_added_count > 0 or .actions_removed_count > 0) |
                        "\(.filename)|" +
                        (if .actions_added_count > 0 then "Added: " + (.actions_added | join(", ")) else "" end) +
                        (if (.actions_added_count > 0 and .actions_removed_count > 0) then "; " else "" end) +
                        (if .actions_removed_count > 0 then "Removed: " + (.actions_removed | join(", ")) else "" end)' \
                        "${REPORT_FILE}" 2>/dev/null | while IFS='|' read -r filename changes; do
                        echo "- **${filename}:** ${changes}" >> "${files_added_file}"
                    done
                    echo "" >> "${files_added_file}"
                fi
            fi

            echo '```' >> "${files_added_file}"
            find "${mcc_dir}/resources/sts" -type f -name "*.json" 2>/dev/null | sed "s|${mcc_dir}/||" | sort | sed 's/^/- /' >> "${files_added_file}"
            echo '```' >> "${files_added_file}"
            echo >> "${files_added_file}"
        fi

        # List GCP WIF files
        if [ ${gcp_wif_count} -gt 0 ]; then
            echo "### GCP Workload Identity Templates (${gcp_wif_count})" >> "${files_added_file}"
            echo '```' >> "${files_added_file}"
            find "${mcc_dir}/resources/wif" -type f -name "*.yaml" 2>/dev/null | sed "s|${mcc_dir}/||" | sort | sed 's/^/- /' >> "${files_added_file}"
            echo '```' >> "${files_added_file}"
            echo >> "${files_added_file}"
        fi

        # List acknowledgment files
        if [ ${ack_count} -gt 0 ]; then
            echo "### Acknowledgment Files (${ack_count})" >> "${files_added_file}"
            echo '```' >> "${files_added_file}"
            find "${mcc_dir}/deploy/osd-cluster-acks" -type f \( -name "config.yaml" -o -name "*ack*.yaml" \) 2>/dev/null | sed "s|${mcc_dir}/||" | sort | sed 's/^/- /' >> "${files_added_file}"
            echo '```' >> "${files_added_file}"
            echo >> "${files_added_file}"
        fi

        # Add note if OCP has no gates
        if [ "${ocp_has_gates}" = "false" ]; then
            echo "**Note:** No OCP admin gates found for version ${version} - no OCP acknowledgment files created." >> "${files_added_file}"
            echo >> "${files_added_file}"
        fi
    fi

    # Generate final PR body with placeholder replacements
    local pr_body_file=$(mktemp)
    trap "rm -f '${failure_summary_file}' '${files_added_file}' '${pr_body_file}'" RETURN

    # Use awk to replace placeholders (more reliable than bash string replacement for multi-line content)
    awk -v target="${target}" \
        -v baseline="${baseline}" \
        -v prow_url="${prow_job_url}" \
        -v html_url="${html_report_url}" \
        -v aws_count="${aws_sts_count}" \
        -v gcp_count="${gcp_wif_count}" \
        -v ack_count="${ack_count}" \
        -v total="${total_files}" \
        -v failure_file="${failure_summary_file}" \
        -v files_file="${files_added_file}" '
    {
        line = $0
        gsub(/\{\{TARGET_VERSION\}\}/, target, line)
        gsub(/\{\{BASELINE_VERSION\}\}/, baseline, line)
        gsub(/\{\{PROW_JOB_URL\}\}/, prow_url, line)
        gsub(/\{\{HTML_REPORT_URL\}\}/, html_url, line)
        gsub(/\{\{AWS_STS_COUNT\}\}/, aws_count, line)
        gsub(/\{\{GCP_WIF_COUNT\}\}/, gcp_count, line)
        gsub(/\{\{ACK_COUNT\}\}/, ack_count, line)
        gsub(/\{\{TOTAL_FILES\}\}/, total, line)

        if (line ~ /\{\{FAILURE_SUMMARY\}\}/) {
            while ((getline failure_line < failure_file) > 0) {
                print failure_line
            }
            close(failure_file)
        } else if (line ~ /\{\{FILES_ADDED\}\}/) {
            while ((getline files_line < files_file) > 0) {
                print files_line
            }
            close(files_file)
        } else {
            print line
        }
    }' "${template_file}"
}

# Create PR
create_pr() {
    log_info "Creating pull request..."

    # Validate prerequisites
    if [ -z "${FORK_REPO}" ]; then
        log_error "Fork repository is required for PR creation. Use --fork-repo flag."
        exit 1
    fi

    if [ -z "${GITHUB_USERNAME}" ]; then
        log_error "GITHUB_USERNAME is required for PR creation."
        log_error "Set it in .github-pr-config file."
        exit 1
    fi

    if [ -z "${GIT_USER_NAME}" ] || [ -z "${GIT_USER_EMAIL}" ]; then
        log_error "GIT_USER_NAME and GIT_USER_EMAIL are required for commits."
        log_error "Set them in .github-pr-config file."
        exit 1
    fi

    # Determine target repository
    local actual_target
    if [ "${USE_TEST_MODE}" = true ]; then
        if [ -z "${TEST_REPO}" ]; then
            log_error "Test mode requires TEST_REPO to be set"
            log_error "Set it in .github-pr-config or use --test-repo flag"
            exit 1
        fi
        actual_target="${TEST_REPO}"
        log_warn "⚠️  TEST MODE: Creating PR against ${actual_target}"
    else
        actual_target="${TARGET_REPO}"
        log_info "Production mode: Creating PR against ${actual_target}"
    fi

    # Validate GitHub prerequisites
    validate_github_prerequisites "${actual_target}"

    # Extract version information from report
    local version baseline_version target_version
    version=$(jq -r '.target' "${REPORT_FILE}" | grep -oP '^\d+\.\d+')
    baseline_version=$(jq -r '.baseline' "${REPORT_FILE}" 2>/dev/null || echo "unknown")
    target_version=$(jq -r '.target' "${REPORT_FILE}" 2>/dev/null || echo "${version}")

    # Extract Prow job ID from failure-summary.md or environment
    local prow_job_id="${PROW_JOB_ID}"
    if [ -z "${prow_job_id}" ] && [ -f "${WORK_DIR}/failure-summary.md" ]; then
        prow_job_id=$(grep "Job ID:" "${WORK_DIR}/failure-summary.md" 2>/dev/null | grep -oE '[0-9]{10,}' | head -1 || echo "")
    fi

    # Extract job name from prowjob.json if available, otherwise use default
    local prow_job_name="periodic-ci-openshift-online-rosa-gap-analysis-main-nightly"
    local prowjob_json="${WORK_DIR}/prowjob.json"
    if [ -f "${prowjob_json}" ]; then
        prow_job_name=$(jq -r '.spec.job' "${prowjob_json}" 2>/dev/null || echo "${prow_job_name}")
    fi

    # Get exact HTML report filename from work directory
    local html_report_filename=""
    if [ -n "${prow_job_id}" ]; then
        html_report_filename=$(find "${WORK_DIR}" -name "gap-analysis-full_${baseline_version}_to_${target_version}_*.html" -type f -printf '%f\n' | head -1 || echo "")
    fi

    # Construct Prow job URL and HTML report URL
    local prow_job_url="N/A"
    local html_report_url="N/A"
    if [ -n "${prow_job_id}" ]; then
        prow_job_url="https://prow.ci.openshift.org/view/gs/test-platform-results/logs/${prow_job_name}/${prow_job_id}"
        if [ -n "${html_report_filename}" ]; then
            html_report_url="https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/test-platform-results/logs/${prow_job_name}/${prow_job_id}/artifacts/test/artifacts/rosa-gap-analysis-reports/${html_report_filename}"
        else
            html_report_url="https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/test-platform-results/logs/${prow_job_name}/${prow_job_id}/artifacts/test/artifacts/rosa-gap-analysis-reports/"
        fi
    elif [ -n "${PROW_JOB_URL}" ]; then
        prow_job_url="${PROW_JOB_URL}"
    fi

    # Create temporary work directory in /tmp
    local work_dir
    work_dir=$(mktemp -d -t gap-pr-XXXXXXXXXX)

    # Set up cleanup trap
    trap "cd '${PROJECT_ROOT}' 2>/dev/null; rm -rf '${work_dir}'" EXIT

    local source_dir="${WORK_DIR}/managed-cluster-config"
    local branch_name="ocp-${version}-gap-analysis-update"

    log_info "Using work directory: ${work_dir}"

    if [ "${DRY_RUN}" = true ]; then
        log_warn "[DRY RUN] Would create PR:"
        log_warn "  Target: ${actual_target}"
        log_warn "  Fork: ${FORK_REPO}"
        log_warn "  Branch: ${branch_name}"
        log_warn "  Version: ${version}"
        log_warn "  Work dir: ${work_dir}"
        return 0
    fi

    # Clone fork
    log_info "Cloning fork repository: ${FORK_REPO}..."
    if ! gh repo clone "${FORK_REPO}" "${work_dir}"; then
        log_error "Failed to clone fork repository"
        exit 1
    fi

    cd "${work_dir}"

    # Configure git user for commits (bot identity in temp directory)
    log_info "Setting local git config in work directory:"
    log_info "  user.name  = ${GIT_USER_NAME}"
    log_info "  user.email = ${GIT_USER_EMAIL}"
    git config user.name "${GIT_USER_NAME}"
    git config user.email "${GIT_USER_EMAIL}"

    # Disable askpass to prevent credential prompts
    git config core.askPass ""
    export GIT_TERMINAL_PROMPT=0
    unset SSH_ASKPASS
    unset GIT_ASKPASS

    log_success "✓ Git user configured for commits"

    # Add upstream remote
    git remote add upstream "https://github.com/${actual_target}.git" 2>/dev/null || true
    git fetch upstream

    # Create branch from upstream default branch
    local default_branch
    # Get upstream's default branch (not origin's)
    default_branch=$(git symbolic-ref refs/remotes/upstream/HEAD 2>/dev/null | sed 's@^refs/remotes/upstream/@@')

    # If upstream/HEAD doesn't exist, use 'master' as fallback
    if [ -z "${default_branch}" ]; then
        log_warn "Could not detect upstream default branch, using 'master'"
        default_branch="master"
    fi

    log_info "Using upstream branch: ${default_branch}"

    # Checkout upstream default branch
    git checkout -b "temp-${default_branch}" "upstream/${default_branch}"

    if git show-ref --verify --quiet "refs/heads/${branch_name}"; then
        git branch -D "${branch_name}"
    fi

    git checkout -b "${branch_name}" "upstream/${default_branch}"
    log_success "✓ Branch created: ${branch_name}"

    # Clean up temp branch
    git branch -D "temp-${default_branch}" 2>/dev/null || true

    # Copy files (add/update only, don't delete existing files)
    log_info "Copying generated files..."
    rsync -av --exclude='.git' "${source_dir}/" ./ 2>&1 | grep -v "sending incremental file list" || true
    log_success "✓ Files copied"

    # Run make to generate additional files
    log_info "Running 'make' to generate additional files..."
    if [ -f Makefile ] || [ -f makefile ]; then
        if make 2>&1 | tee /tmp/make-output.log; then
            log_success "✓ Make completed successfully"

            # Show what files were generated
            local generated_files
            generated_files=$(git status --short 2>/dev/null | grep -E "^\?\?|^ M|^ A" | wc -l)
            if [ "${generated_files}" -gt 0 ]; then
                log_info "Make generated/modified ${generated_files} additional file(s)"
                git status --short 2>/dev/null | grep -E "^\?\?|^ M|^ A" | head -10
            else
                log_info "No additional files generated by make"
            fi
        else
            log_error "Make command failed!"
            log_error "Output saved to /tmp/make-output.log"
            cat /tmp/make-output.log >&2
            exit 1
        fi
    else
        log_warn "No Makefile found - skipping make step"
    fi

    # Stage all changed files (including make-generated files)
    log_info "Staging all changed files..."
    if ! git add -A; then
        log_error "Failed to stage files"
        exit 1
    fi
    log_success "✓ Files staged"

    # Count gap-analysis generated files for commit message (exclude make-generated)
    log_info "Counting gap-analysis generated files..."
    log_info "Version for counting: ${version}"
    local aws_sts_count=0
    local gcp_wif_count=0
    local ack_count=0

    if [ -d "resources/sts/${version}" ]; then
        log_info "Counting AWS STS files in resources/sts/${version}..."
        aws_sts_count=$(find "resources/sts/${version}" -type f -name "*.json" 2>/dev/null | wc -l)
        log_info "AWS STS count: ${aws_sts_count}"
    fi
    if [ -d "resources/wif/${version}" ]; then
        log_info "Counting GCP WIF files in resources/wif/${version}..."
        gcp_wif_count=$(find "resources/wif/${version}" -type f -name "*.yaml" 2>/dev/null | wc -l)
        log_info "GCP WIF count: ${gcp_wif_count}"
    fi
    if [ -d "deploy/osd-cluster-acks" ]; then
        log_info "Counting ack files in deploy/osd-cluster-acks..."
        # Count ack files in sts, wif, and ocp directories for this version
        local sts_acks=0
        local wif_acks=0
        local ocp_acks=0
        [ -d "deploy/osd-cluster-acks/sts/${version}" ] && sts_acks=$(find "deploy/osd-cluster-acks/sts/${version}" -type f -name "*.yaml" 2>/dev/null | wc -l)
        [ -d "deploy/osd-cluster-acks/wif/${version}" ] && wif_acks=$(find "deploy/osd-cluster-acks/wif/${version}" -type f -name "*.yaml" 2>/dev/null | wc -l)
        [ -d "deploy/osd-cluster-acks/ocp/${version}" ] && ocp_acks=$(find "deploy/osd-cluster-acks/ocp/${version}" -type f -name "*.yaml" 2>/dev/null | wc -l)
        ack_count=$((sts_acks + wif_acks + ocp_acks))
        log_info "Ack count: ${ack_count} (STS:${sts_acks}, WIF:${wif_acks}, OCP:${ocp_acks})"
    fi
    log_info "Counts: AWS STS=${aws_sts_count}, GCP WIF=${gcp_wif_count}, Acks=${ack_count}"

    # Filter out empty files that might have been staged
    log_info "Filtering empty files..."
    for file in $(git diff --cached --name-only 2>/dev/null); do
        if [ ! -s "${file}" ]; then
            log_warn "Unstaging empty file: ${file}"
            git reset HEAD "${file}" 2>/dev/null || true
        fi
    done
    log_success "✓ Empty files filtered"

    log_info "Creating commit..."
    local commit_msg
    commit_msg="Add OCP ${version} Gap Analysis files

- AWS STS IAM policies: ${aws_sts_count} file(s)
- GCP WIF templates: ${gcp_wif_count} file(s)
- Acknowledgment files: ${ack_count} file(s)

Addresses gap-analysis validation failures for OCP ${version}.

Co-Authored-By: ${GIT_USER_NAME} <${GIT_USER_EMAIL}}"

    if ! git commit -m "${commit_msg}"; then
        log_error "Failed to create commit"
        exit 1
    fi
    log_success "✓ Commit created"

    # Configure origin remote to use token for authentication
    local token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
    local origin_url="https://${GITHUB_USERNAME}:${token}@github.com/${FORK_REPO}.git"
    log_info "Configuring origin remote with token authentication"
    git remote set-url origin "${origin_url}"

    # Push to fork
    log_info "Pushing to fork: ${FORK_REPO}"
    git push -u origin "${branch_name}" --force
    log_success "✓ Pushed to origin/${branch_name}"

    # Return to project root to create PR (avoid repository context confusion)
    cd "${PROJECT_ROOT}"

    # Re-authenticate as bot for PR creation (in case auth changed)
    local token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
    log_info "Ensuring authentication as ${GITHUB_USERNAME} for PR creation"
    echo "${token}" | gh auth login --with-token 2>/dev/null || true

    # Verify we're authenticated as the correct user
    local current_user
    current_user=$(gh api user --jq '.login' 2>/dev/null)
    if [ "${current_user}" != "${GITHUB_USERNAME}" ]; then
        log_error "GitHub authentication check failed before PR creation"
        log_error "  Expected: ${GITHUB_USERNAME}"
        log_error "  Actual: ${current_user}"
        exit 1
    fi
    log_success "✓ Authenticated as ${current_user} for PR creation"

    # Extract fork owner for PR creation
    local fork_owner="${FORK_REPO%%/*}"

    # Check if PR already exists
    log_info "Checking for existing PR from ${fork_owner}:${branch_name} to ${actual_target}"
    local existing_pr
    existing_pr=$(gh pr list --repo "${actual_target}" --json url,headRefName,headRepositoryOwner --jq ".[] | select(.headRepositoryOwner.login == \"${fork_owner}\" and .headRefName == \"${branch_name}\") | .url" 2>/dev/null | head -1 || echo "")

    if [ -n "${existing_pr}" ]; then
        log_warn "⚠️  PR already exists for branch ${branch_name}"
        log_success "Existing PR URL: ${existing_pr}"
        echo "${existing_pr}" > "${WORK_DIR}/pr-url.txt"
        log_info ""
        log_info "======================================================================"
        log_success "✅ PR already exists - no duplicate created"
        log_info ""
        log_info "PR URL: ${existing_pr}"
        log_info "Branch: ${fork_owner}:${branch_name} → ${actual_target}:${default_branch}"
        return 0
    fi

    log_info "No existing PR found - proceeding with creation"

    # Generate PR body from template
    log_info "Generating PR description..."
    local pr_body
    pr_body=$(generate_pr_body "${version}" "${baseline_version}" "${target_version}" "${prow_job_url}" "${html_report_url}" "${ocp_has_gates}")

    log_info "Creating pull request to ${actual_target}"
    local gh_args=()
    gh_args+=(--repo "${actual_target}")
    gh_args+=(--title "Add OCP ${version} Gap Analysis files")
    gh_args+=(--body "${pr_body}")
    gh_args+=(--base "${default_branch}")
    gh_args+=(--head "${fork_owner}:${branch_name}")

    if [ -n "${LABELS}" ]; then
        gh_args+=(--label "${LABELS}")
    fi

    # Add reviewers only if not empty
    # Note: Reviewer assignment may fail if bot lacks permissions
    local reviewer_args=()
    if [ -n "${REVIEWERS}" ]; then
        reviewer_args+=(--reviewer "${REVIEWERS}")
    fi

    # Debug: show the command
    log_info "gh pr create command: ${gh_args[*]} ${reviewer_args[*]}"

    # Ensure we're using the bot's token for PR creation
    local token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
    local pr_url

    # Try to create PR with reviewers first
    if [ ${#reviewer_args[@]} -gt 0 ]; then
        pr_url=$(GH_TOKEN="${token}" gh pr create "${gh_args[@]}" "${reviewer_args[@]}" 2>&1)
        local pr_exit_code=$?

        # If reviewer assignment failed, try without reviewers
        if [ ${pr_exit_code} -ne 0 ] && echo "${pr_url}" | grep -q "does not have the correct permissions"; then
            log_warn "⚠️  Cannot assign reviewers (permission denied), creating PR without reviewers"
            pr_url=$(GH_TOKEN="${token}" gh pr create "${gh_args[@]}" 2>&1)
            pr_exit_code=$?
        fi

        # Check if PR already exists (gh pr create detected it)
        if [ ${pr_exit_code} -ne 0 ] && echo "${pr_url}" | grep -q "already exists"; then
            # Extract PR URL from the "already exists" message
            local existing_url
            existing_url=$(echo "${pr_url}" | grep -oP 'https://github\.com/[^[:space:]]+')
            if [ -n "${existing_url}" ]; then
                log_warn "⚠️  PR already exists (detected by gh pr create)"
                pr_url="${existing_url}"
                pr_exit_code=0
            fi
        fi

        # If still failed, error out
        if [ ${pr_exit_code} -ne 0 ]; then
            echo "${pr_url}" >&2
            return 1
        fi
    else
        pr_url=$(GH_TOKEN="${token}" gh pr create "${gh_args[@]}" 2>&1)
        local pr_exit_code=$?

        # Check if PR already exists
        if [ ${pr_exit_code} -ne 0 ] && echo "${pr_url}" | grep -q "already exists"; then
            local existing_url
            existing_url=$(echo "${pr_url}" | grep -oP 'https://github\.com/[^[:space:]]+')
            if [ -n "${existing_url}" ]; then
                log_warn "⚠️  PR already exists (detected by gh pr create)"
                pr_url="${existing_url}"
                pr_exit_code=0
            fi
        fi

        if [ ${pr_exit_code} -ne 0 ]; then
            echo "${pr_url}" >&2
            return 1
        fi
    fi

    log_success "✓ Pull request created!"
    log_success "PR URL: ${pr_url}"

    echo "${pr_url}" > "${WORK_DIR}/pr-url.txt"

    # Return to project root before cleanup (trap will clean work_dir)
    cd "${PROJECT_ROOT}"
    log_success "✓ Work directory will be cleaned up automatically"
}

# Main
main() {
    log_info "Prow Failure Fix Tool"
    log_info "======================================================================"

    load_config
    parse_args "$@"

    # Validate work directory is provided
    if [ -z "${WORK_DIR}" ]; then
        log_error "Work directory is required."
        log_error ""
        log_error "Provide work directory via:"
        log_error "  1. --work-dir parameter"
        log_error "  2. GAP_WORK_DIR environment variable"
        log_error ""
        log_error "Example workflows:"
        log_error "  # Back-to-back (recommended)"
        log_error "  WORK_DIR=\$(./ci/analyze-prow-failure.sh --keep-work-dir | tail -1) && \\"
        log_error "    ./ci/fix-prow-failure.sh --work-dir \"\$WORK_DIR\" --create-pr"
        log_error ""
        log_error "  # Manual review"
        log_error "  ./ci/analyze-prow-failure.sh --work-dir ~/prow-analysis"
        log_error "  ./ci/fix-prow-failure.sh --work-dir ~/prow-analysis --create-pr"
        exit 1
    fi

    # Create work directory if it doesn't exist
    if [ ! -d "${WORK_DIR}" ]; then
        log_info "Creating work directory: ${WORK_DIR}"
        mkdir -p "${WORK_DIR}"
    fi

    # Check if work directory is a temp directory that should be cleaned up
    if [[ "${WORK_DIR}" == /tmp/gap-analysis-* ]]; then
        CLEANUP_WORK_DIR=true
        log_info "Using temporary work directory: ${WORK_DIR}"
        log_info "Will cleanup after successful PR creation"
    else
        log_info "Using work directory: ${WORK_DIR}"
    fi

    find_latest_report

    # Step 1: Generate fixes
    generate_fixes

    # Step 2: Validate (unless skipped)
    if [ "${SKIP_VALIDATION}" = false ]; then
        validate_fixes
    else
        log_warn "Skipping validation (--skip-validation)"
    fi

    # Step 3: Create PR (if requested)
    if [ "${AUTO_PR}" = true ]; then
        create_pr
    else
        log_info ""
        log_info "Files generated and validated successfully!"
        log_info "To create PR, run:"
        log_info "  $(basename "$0") --create-pr"
    fi

    log_info ""
    log_info "======================================================================"
    log_success "✅ Complete!"

    if [ "${AUTO_PR}" = false ]; then
        log_success ""
        log_success "Generated files: ${WORK_DIR}/managed-cluster-config/"
        log_success ""
        log_success "Next steps:"
        log_success "  1. Review generated files"
        log_success "  2. Run with --create-pr to create PR"
        log_success "  3. Or manually copy files to target repository"
    else
        # PR was created successfully
        if [ "${CLEANUP_WORK_DIR}" = true ]; then
            log_info ""
            log_info "Cleaning up temporary work directory: ${WORK_DIR}"
            rm -rf "${WORK_DIR}"
            log_success "✓ Temporary directory cleaned up"
        else
            log_info ""
            log_info "Work directory preserved: ${WORK_DIR}"
            log_info "You can review the files or manually clean up when done"
        fi
    fi
}

main "$@"
