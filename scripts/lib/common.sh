#!/bin/bash
# Common utility functions for gap analysis scripts

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions (all write to stderr to avoid mixing with data output)
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" >&2
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Check if required command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "Required command '$1' not found. Please install it."
        exit 1
    fi
}

# Parse version/platform argument (e.g., "4.14/osd-aws")
parse_version_platform() {
    local input="$1"
    local version=$(echo "$input" | cut -d'/' -f1)
    local platform=$(echo "$input" | cut -d'/' -f2)

    echo "$version|$platform"
}

# Create output directory if it doesn't exist
ensure_dir() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
        log_info "Created directory: $dir"
    fi
}

# Generate report header
generate_report_header() {
    local baseline="$1"
    local target="$2"
    local report_type="$3"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    cat <<EOF
# ${report_type} Gap Analysis Report

**Baseline**: ${baseline}
**Target**: ${target}
**Generated**: ${timestamp}

---

EOF
}

# Generate report summary section
generate_summary_section() {
    local total="$1"
    local added="$2"
    local removed="$3"
    local changed="$4"

    cat <<EOF
## Summary

- **Total gaps found**: ${total}
- **Added**: ${added}
- **Removed**: ${removed}
- **Changed**: ${changed}

---

EOF
}

# Compare two JSON files and extract differences
# Usage: compare_json baseline.json target.json
compare_json() {
    local baseline="$1"
    local target="$2"

    jq -s '.[0] as $baseline | .[1] as $target | {
        "added": ($target | keys) - ($baseline | keys),
        "removed": ($baseline | keys) - ($target | keys),
        "common": (($baseline | keys) + ($target | keys)) | unique
    }' "$baseline" "$target"
}

# Compare STS/IAM policies in detail
# Usage: compare_sts_policies baseline.json target.json
compare_sts_policies() {
    local baseline="$1"
    local target="$2"

    jq -n --slurpfile baseline "$baseline" --slurpfile target "$target" '
    # Extract all actions from statements
    def extract_actions:
        [.Statement[]? |
         if .Action then
            (if (.Action | type) == "string" then [.Action] else .Action end)
         else [] end
        ] | flatten | unique | sort;

    # Extract statement details for comparison
    def statement_key:
        {
            actions: (if .Action then (if (.Action | type) == "string" then [.Action] else .Action end | sort) else [] end),
            resources: (if .Resource then (if (.Resource | type) == "string" then [.Resource] else .Resource end | sort) else [] end),
            effect: .Effect
        };

    $baseline[0] as $b | $target[0] as $t |

    {
        summary: {
            baseline_statement_count: ($b.Statement | length),
            target_statement_count: ($t.Statement | length),
            baseline_action_count: ($b | extract_actions | length),
            target_action_count: ($t | extract_actions | length)
        },

        # Compare actions
        actions: {
            baseline_only: (($b | extract_actions) - ($t | extract_actions)),
            target_only: (($t | extract_actions) - ($b | extract_actions)),
            common: (($b | extract_actions) as $ba | ($t | extract_actions) as $ta |
                     [$ba[], $ta[]] | unique | map(select(. as $item | $ba | index($item)) | select(. as $item | $ta | index($item))))
        },

        # Group actions by AWS service
        services: {
            baseline: ($b | extract_actions | map(split(":")[0]) | unique | sort),
            target: ($t | extract_actions | map(split(":")[0]) | unique | sort),
            added: (($t | extract_actions | map(split(":")[0]) | unique) -
                    ($b | extract_actions | map(split(":")[0]) | unique)),
            removed: (($b | extract_actions | map(split(":")[0]) | unique) -
                      ($t | extract_actions | map(split(":")[0]) | unique))
        },

        # Detailed statement comparison
        statements: {
            baseline: [$b.Statement[]? | statement_key],
            target: [$t.Statement[]? | statement_key]
        }
    }
    '
}

# Format policy comparison for markdown report
# Usage: format_sts_comparison_report comparison.json
format_sts_comparison_report() {
    local comparison_file="$1"

    # Get added actions
    local added_actions=$(jq -r '.actions.target_only[]? // empty' "$comparison_file")
    local removed_actions=$(jq -r '.actions.baseline_only[]? // empty' "$comparison_file")
    local added_services=$(jq -r '.services.added[]? // empty' "$comparison_file")
    local removed_services=$(jq -r '.services.removed[]? // empty' "$comparison_file")

    # Count changes
    local added_count=$(jq '.actions.target_only | length' "$comparison_file")
    local removed_count=$(jq '.actions.baseline_only | length' "$comparison_file")
    local changed_count=0

    echo "## Summary"
    echo ""
    echo "- **Total permission changes**: $((added_count + removed_count))"
    echo "- **Added permissions**: ${added_count}"
    echo "- **Removed permissions**: ${removed_count}"
    echo "- **Changed permissions**: ${changed_count}"
    echo ""
    echo "---"
    echo ""

    # Added permissions section
    if [[ $added_count -gt 0 ]]; then
        echo "## Added Permissions"
        echo ""
        echo "> New IAM permissions required in the target version"
        echo ""

        # Group by service
        local current_service=""
        while IFS= read -r action; do
            if [[ -z "$action" ]]; then
                continue
            fi

            local service=$(echo "$action" | cut -d: -f1)
            local permission=$(echo "$action" | cut -d: -f2)

            if [[ "$service" != "$current_service" ]]; then
                if [[ -n "$current_service" ]]; then
                    echo ""
                fi
                echo "### ${service} Service"
                echo ""
                current_service="$service"
            fi

            echo "- \`${action}\`"
        done <<< "$added_actions"

        echo ""
        echo "---"
        echo ""
    fi

    # Removed permissions section
    if [[ $removed_count -gt 0 ]]; then
        echo "## Removed Permissions"
        echo ""
        echo "> Permissions no longer required in the target version"
        echo ""

        while IFS= read -r action; do
            if [[ -z "$action" ]]; then
                continue
            fi
            echo "- \`${action}\`"
        done <<< "$removed_actions"

        echo ""
        echo "---"
        echo ""
    fi

    # Service changes
    if [[ -n "$added_services" ]] || [[ -n "$removed_services" ]]; then
        echo "## Service-Level Changes"
        echo ""

        if [[ -n "$added_services" ]]; then
            echo "### New AWS Services Required"
            echo ""
            while IFS= read -r service; do
                if [[ -z "$service" ]]; then
                    continue
                fi
                echo "- **${service}**: New service integration"
            done <<< "$added_services"
            echo ""
        fi

        if [[ -n "$removed_services" ]]; then
            echo "### AWS Services No Longer Used"
            echo ""
            while IFS= read -r service; do
                if [[ -z "$service" ]]; then
                    continue
                fi
                echo "- **${service}**: Service no longer required"
            done <<< "$removed_services"
            echo ""
        fi

        echo "---"
        echo ""
    fi
}

# Export new functions
export -f compare_sts_policies format_sts_comparison_report

# Get project root directory
# This function should be called from scripts that have already set SCRIPT_DIR
get_project_root() {
    # Use SCRIPT_DIR if available (set by calling script)
    if [[ -n "${SCRIPT_DIR:-}" ]]; then
        cd "$SCRIPT_DIR/.." && pwd
        return
    fi

    # Fallback: navigate from current directory
    local current="$PWD"
    while [[ "$current" != "/" ]]; do
        if [[ -f "$current/README.md" ]] && [[ -d "$current/scripts" ]]; then
            echo "$current"
            return
        fi
        current="$(dirname "$current")"
    done

    # Last resort: assume we're in scripts/ or scripts/lib/
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# Export functions for use in other scripts
export -f log_info log_success log_warning log_error
export -f check_command parse_version_platform ensure_dir
export -f generate_report_header generate_summary_section
export -f get_project_root
