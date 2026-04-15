#!/bin/bash

# =============================================================================
# Library: parser.sh
# Description: Parse gap-analysis JSON reports and extract failure information
# =============================================================================

set -euo pipefail

# Parse combined gap-analysis JSON report
# Args: $1 = path to gap-analysis-full_*.json
# Returns: JSON object with parsed failure information
parse_gap_report() {
    local report_path="$1"

    if [ ! -f "${report_path}" ]; then
        echo "ERROR: Report file not found: ${report_path}" >&2
        return 1
    fi

    if ! jq empty "${report_path}" 2>/dev/null; then
        echo "ERROR: Invalid JSON in report file" >&2
        return 1
    fi

    jq '{
        baseline: .baseline,
        target: .target,
        timestamp: .timestamp,
        aws_sts: .aws_sts,
        gcp_wif: .gcp_wif,
        ocp_gate_ack: .ocp_gate_ack,
        feature_gates: .feature_gates
    }' "${report_path}"
}

# Extract AWS STS failures
# Args: $1 = path to gap-analysis-full_*.json
# Returns: JSON object with AWS STS failure details
extract_aws_sts_failures() {
    local report_path="$1"

    jq '.aws_sts | {
        validation_failed: (.validation_details.valid == false),
        resources_failed: (.validation_details.check_1_resources.valid == false),
        admin_ack_failed: (.validation_details.check_2_admin_ack.valid == false),
        resources_errors: [.validation_details.check_1_resources.errors[]? // empty],
        admin_ack_errors: [.validation_details.check_2_admin_ack.errors[]? // empty],
        added_permissions: [.comparison.actions.target_only[]? // empty],
        removed_permissions: [.comparison.actions.baseline_only[]? // empty],
        changed_files: .comparison.file_changes
    }' "${report_path}"
}

# Extract GCP WIF failures
# Args: $1 = path to gap-analysis-full_*.json
# Returns: JSON object with GCP WIF failure details
extract_gcp_wif_failures() {
    local report_path="$1"

    jq '.gcp_wif | {
        validation_failed: (.validation_details.valid == false),
        resources_failed: (.validation_details.check_1_resources.valid == false),
        admin_ack_failed: (.validation_details.check_2_admin_ack.valid == false),
        resources_errors: [.validation_details.check_1_resources.errors[]? // empty],
        admin_ack_errors: [.validation_details.check_2_admin_ack.errors[]? // empty],
        added_permissions: [.comparison.actions.target_only[]? // empty],
        removed_permissions: [.comparison.actions.baseline_only[]? // empty],
        changed_files: .comparison.file_changes
    }' "${report_path}"
}

# Extract OCP Gate Ack failures
# Args: $1 = path to gap-analysis-full_*.json
# Returns: JSON object with OCP gate ack failure details
extract_ocp_gate_failures() {
    local report_path="$1"

    jq '.ocp_gate_ack | {
        validation_failed: (.validation_details.valid == false),
        config_errors: [.validation_details.errors[]? // empty],
        requiring_ack: [.comparison.requiring_ack[]? // empty],
        unacknowledged: [.comparison.unacknowledged[]? // empty]
    }' "${report_path}"
}

# Generate missing files list for AWS STS
# Args: $1 = target_version, $2 = aws_sts_failures_json
# Returns: List of missing file paths
generate_aws_sts_missing_files() {
    local target_version="$1"
    local failures="$2"
    local target_minor

    # Extract minor version (4.22.0-ec.4 -> 4.22)
    target_minor=$(echo "${target_version}" | grep -oP '^\d+\.\d+')

    local resources_failed
    local admin_ack_failed

    resources_failed=$(echo "${failures}" | jq -r '.resources_failed')
    admin_ack_failed=$(echo "${failures}" | jq -r '.admin_ack_failed')

    # Build missing files list
    local missing_files=()

    if [ "${resources_failed}" = "true" ]; then
        missing_files+=("resources/sts/${target_minor}/")
        missing_files+=("resources/sts/${target_minor}/*.yaml")
    fi

    if [ "${admin_ack_failed}" = "true" ]; then
        missing_files+=("deploy/osd-cluster-acks/sts/${target_minor}/config.yaml")
        missing_files+=("deploy/osd-cluster-acks/sts/${target_minor}/osd-sts-ack_CloudCredential.yaml")
    fi

    printf '%s\n' "${missing_files[@]}"
}

# Generate missing files list for GCP WIF
# Args: $1 = target_version, $2 = gcp_wif_failures_json
# Returns: List of missing file paths
generate_gcp_wif_missing_files() {
    local target_version="$1"
    local failures="$2"
    local target_minor

    # Extract minor version
    target_minor=$(echo "${target_version}" | grep -oP '^\d+\.\d+')

    local resources_failed
    local admin_ack_failed

    resources_failed=$(echo "${failures}" | jq -r '.resources_failed')
    admin_ack_failed=$(echo "${failures}" | jq -r '.admin_ack_failed')

    # Build missing files list
    local missing_files=()

    if [ "${resources_failed}" = "true" ]; then
        missing_files+=("resources/wif/${target_minor}/")
        missing_files+=("resources/wif/${target_minor}/*.yaml")
    fi

    if [ "${admin_ack_failed}" = "true" ]; then
        missing_files+=("deploy/osd-cluster-acks/wif/${target_minor}/config.yaml")
        missing_files+=("deploy/osd-cluster-acks/wif/${target_minor}/cloudcredential.yaml")
    fi

    printf '%s\n' "${missing_files[@]}"
}

# Generate missing files list for OCP Gate Ack
# Args: $1 = target_version, $2 = ocp_gate_failures_json
# Returns: List of missing file paths
generate_ocp_gate_missing_files() {
    local target_version="$1"
    local failures="$2"
    local target_minor

    # Extract minor version
    target_minor=$(echo "${target_version}" | grep -oP '^\d+\.\d+')

    local config_failed
    config_failed=$(echo "${failures}" | jq -r '.validation_failed')

    # Build missing files list
    local missing_files=()

    if [ "${config_failed}" = "true" ]; then
        missing_files+=("deploy/osd-cluster-acks/ocp/${target_minor}/config.yaml")
    fi

    # Check if there are unacknowledged gates
    local unacknowledged_count
    unacknowledged_count=$(echo "${failures}" | jq -r '.unacknowledged | length')

    if [ "${unacknowledged_count}" -gt 0 ]; then
        missing_files+=("deploy/osd-cluster-acks/ocp/${target_minor}/cloudcredential.yaml")
    fi

    printf '%s\n' "${missing_files[@]}"
}

# Generate summary report
# Args: $1 = report_path, $2 = job_id, $3 = output_path
generate_failure_summary() {
    local report_path="$1"
    local job_id="$2"
    local output_path="$3"

    local baseline target
    baseline=$(jq -r '.baseline' "${report_path}")
    target=$(jq -r '.target' "${report_path}")

    local target_minor
    target_minor=$(echo "${target}" | grep -oP '^\d+\.\d+')

    # Extract failures
    local aws_failures gcp_failures ocp_failures
    aws_failures=$(extract_aws_sts_failures "${report_path}")
    gcp_failures=$(extract_gcp_wif_failures "${report_path}")
    ocp_failures=$(extract_ocp_gate_failures "${report_path}")

    # Check if any validation failed
    local aws_failed gcp_failed ocp_failed
    aws_failed=$(echo "${aws_failures}" | jq -r '.validation_failed')
    gcp_failed=$(echo "${gcp_failures}" | jq -r '.validation_failed')
    ocp_failed=$(echo "${ocp_failures}" | jq -r '.validation_failed')

    # Start generating summary
    {
        echo "# Gap Analysis Failure Summary"
        echo ""
        echo "**Job ID:** ${job_id}"
        echo "**Baseline Version:** ${baseline}"
        echo "**Target Version:** ${target}"
        echo "**Target Minor Version:** ${target_minor}"
        echo ""
        echo "---"
        echo ""

        if [ "${aws_failed}" = "true" ] || [ "${gcp_failed}" = "true" ] || [ "${ocp_failed}" = "true" ]; then
            echo "## Missing Files in managed-cluster-config"
            echo ""
            echo "The following files and directories need to be created in the [managed-cluster-config](https://github.com/openshift/managed-cluster-config) repository:"
            echo ""
        fi

        # AWS STS section
        if [ "${aws_failed}" = "true" ]; then
            echo "### AWS STS (CHECK #1 & #2)"
            echo ""

            local aws_resources_failed aws_admin_failed
            aws_resources_failed=$(echo "${aws_failures}" | jq -r '.resources_failed')
            aws_admin_failed=$(echo "${aws_failures}" | jq -r '.admin_ack_failed')

            if [ "${aws_resources_failed}" = "true" ]; then
                echo "**Resources Directory:**"
                echo "- \`resources/sts/${target_minor}/\` directory"
                echo "- Policy files: \`resources/sts/${target_minor}/*.yaml\`"
                echo ""
                echo "**Errors:**"
                echo "${aws_failures}" | jq -r '.resources_errors[]? | "- " + .'
                echo ""
            fi

            if [ "${aws_admin_failed}" = "true" ]; then
                echo "**Admin Acknowledgment Files:**"
                echo "- \`deploy/osd-cluster-acks/sts/${target_minor}/config.yaml\`"
                echo "- \`deploy/osd-cluster-acks/sts/${target_minor}/osd-sts-ack_CloudCredential.yaml\`"
                echo ""
                echo "**Errors:**"
                echo "${aws_failures}" | jq -r '.admin_ack_errors[]? | "- " + .'
                echo ""
            fi

            # Show added permissions
            local added_count
            added_count=$(echo "${aws_failures}" | jq -r '.added_permissions | length')
            if [ "${added_count}" -gt 0 ]; then
                echo "**Added Permissions (${added_count}):**"
                echo "${aws_failures}" | jq -r '.added_permissions[] | "- `" + . + "`"'
                echo ""
            fi
        fi

        # GCP WIF section
        if [ "${gcp_failed}" = "true" ]; then
            echo "### GCP WIF (CHECK #3 & #4)"
            echo ""

            local gcp_resources_failed gcp_admin_failed
            gcp_resources_failed=$(echo "${gcp_failures}" | jq -r '.resources_failed')
            gcp_admin_failed=$(echo "${gcp_failures}" | jq -r '.admin_ack_failed')

            if [ "${gcp_resources_failed}" = "true" ]; then
                echo "**Resources Directory:**"
                echo "- \`resources/wif/${target_minor}/\` directory"
                echo "- Template files: \`resources/wif/${target_minor}/*.yaml\`"
                echo ""
                echo "**Errors:**"
                echo "${gcp_failures}" | jq -r '.resources_errors[]? | "- " + .'
                echo ""
            fi

            if [ "${gcp_admin_failed}" = "true" ]; then
                echo "**Admin Acknowledgment Files:**"
                echo "- \`deploy/osd-cluster-acks/wif/${target_minor}/config.yaml\`"
                echo "- \`deploy/osd-cluster-acks/wif/${target_minor}/cloudcredential.yaml\`"
                echo ""
                echo "**Errors:**"
                echo "${gcp_failures}" | jq -r '.admin_ack_errors[]? | "- " + .'
                echo ""
            fi

            # Show added permissions
            local added_count
            added_count=$(echo "${gcp_failures}" | jq -r '.added_permissions | length')
            if [ "${added_count}" -gt 0 ]; then
                echo "**Added Permissions (${added_count}):**"
                echo "${gcp_failures}" | jq -r '.added_permissions[] | "- `" + . + "`"'
                echo ""
            fi
        fi

        # OCP Gate Ack section
        if [ "${ocp_failed}" = "true" ]; then
            echo "### OCP Admin Gates (CHECK #5)"
            echo ""

            echo "**Admin Acknowledgment Files:**"
            echo "- \`deploy/osd-cluster-acks/ocp/${target_minor}/config.yaml\`"
            echo ""

            local unack_count
            unack_count=$(echo "${ocp_failures}" | jq -r '.unacknowledged | length')

            if [ "${unack_count}" -gt 0 ]; then
                echo "- \`deploy/osd-cluster-acks/ocp/${target_minor}/cloudcredential.yaml\`"
                echo ""
                echo "**Unacknowledged Gates (${unack_count}):**"
                echo "${ocp_failures}" | jq -r '.unacknowledged[] | "- `" + . + "`"'
                echo ""
            fi

            echo "**Errors:**"
            echo "${ocp_failures}" | jq -r '.config_errors[]? | "- " + .'
            echo ""
        fi

        # Summary section
        echo "---"
        echo ""
        echo "## Next Steps"
        echo ""
        echo "1. **Create missing directories and files** in managed-cluster-config repository"
        echo "2. **Extract credential requests** from OCP release ${target}"
        echo "   \`\`\`bash"
        echo "   oc adm release extract --credentials-requests --to=extracted/ quay.io/openshift-release-dev/ocp-release:${target}"
        echo "   \`\`\`"
        echo "3. **Create policy files** based on extracted CredentialsRequest manifests"
        echo "4. **Create acknowledgment files** (config.yaml, cloudcredential.yaml)"
        echo "5. **Submit PR** to managed-cluster-config repository"
        echo ""
        echo "## Full Report"
        echo ""

        # Extract work directory from output path
        local work_dir
        work_dir=$(dirname "${output_path}")

        echo "View the complete gap analysis report for detailed changes:"
        echo "- HTML Report: \`${work_dir}/gap-analysis-full_${baseline}_to_${target}_*.html\`"
        echo "- JSON Report: \`${work_dir}/gap-analysis-full_${baseline}_to_${target}_*.json\`"

    } > "${output_path}"
}
