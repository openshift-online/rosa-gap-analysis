#!/usr/bin/env python3
"""GCP WIF Policy Gap Analysis - Compare WIF policies between OpenShift versions."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info, log_success, log_error, log_warning, check_command
from openshift_releases import resolve_baseline_version, resolve_target_version
from reporters import generate_markdown_report, generate_html_report, generate_json_report


def extract_credential_requests(version, cloud="gcp"):
    """Extract credential requests using oc adm release extract."""
    temp_dir = tempfile.mkdtemp(prefix='ocp-crs-')

    # Construct release image URL
    # If version is just minor (e.g., "4.21"), append .0
    if version.count('.') == 1 and version.replace('.', '').isdigit():
        version = f"{version}.0"

    if version.replace('.', '').replace('-', '').isdigit() or '-rc' in version or '-ec' in version:
        release_image = f"quay.io/openshift-release-dev/ocp-release:{version}-x86_64"
    else:
        release_image = version

    log_info(f"Extracting credential requests from {release_image} for cloud={cloud}")

    try:
        # Run oc adm release extract
        cmd = [
            'oc', 'adm', 'release', 'extract',
            release_image,
            '--credentials-requests',
            f'--cloud={cloud}',
            f'--to={temp_dir}'
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

        # Filter out warnings from stderr
        stderr_lines = [line for line in result.stderr.split('\n') if 'warning:' not in line.lower()]
        if stderr_lines and any(line.strip() for line in stderr_lines):
            for line in stderr_lines:
                if line.strip():
                    print(line, file=sys.stderr)

        if result.returncode != 0:
            log_error(f"Failed to extract credential requests for version {version}")
            return None

        log_success(f"Credential requests extracted to: {temp_dir}")
        return temp_dir

    except Exception as e:
        log_error(f"Failed to extract credential requests: {e}")
        return None


def convert_credential_requests_to_policy(cr_dir):
    """Convert GCP CredentialsRequest YAML files to policy JSON."""
    import glob
    try:
        import yaml
    except ImportError:
        log_error("PyYAML not installed. Please install: pip3 install PyYAML")
        sys.exit(1)

    # Initialize empty permissions list
    all_permissions = []

    # Find all YAML files
    yaml_files = glob.glob(os.path.join(cr_dir, '*.yaml'))

    if not yaml_files:
        log_warning(f"No YAML files found in {cr_dir}")
        return {"Version": "2012-10-17", "Statement": []}

    log_info(f"Processing {len(yaml_files)} credential request file(s)...")

    for yaml_file in yaml_files:
        basename = os.path.basename(yaml_file)

        try:
            with open(yaml_file, 'r') as f:
                cr = yaml.safe_load(f)

            # Extract permissions from GCP providerSpec
            permissions = cr.get('spec', {}).get('providerSpec', {}).get('permissions', [])

            if not permissions:
                continue

            all_permissions.extend(permissions)
            log_info(f"  ✓ Processed {basename}: {len(permissions)} permission(s)")

        except Exception as e:
            log_warning(f"Failed to process {basename}: {e}")
            continue

    # Deduplicate and sort
    unique_permissions = sorted(set(all_permissions))

    # Convert to policy-like format for comparison
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": unique_permissions,
                "Resource": "*"
            }
        ] if unique_permissions else []
    }

    log_success(f"Converted to GCP IAM policy: {len(unique_permissions)} unique permission(s)")
    return policy


def get_wif_policy(version):
    """Get WIF policy for a specific version."""
    log_info(f"Fetching GCP WIF policy for version {version}...")

    # Extract credential requests
    cr_dir = extract_credential_requests(version, 'gcp')
    if not cr_dir:
        sys.exit(1)

    # Convert to policy
    policy = convert_credential_requests_to_policy(cr_dir)

    # Clean up temp directory
    import shutil
    shutil.rmtree(cr_dir, ignore_errors=True)

    # Validate we got data
    if len(policy['Statement']) == 0:
        log_error("No statements found in extracted credential requests")
        sys.exit(1)

    log_success("Successfully extracted WIF policy")
    return policy


def compare_wif_policies(baseline_policy, target_policy):
    """Compare two WIF policies and return differences."""
    # Extract all actions (permissions) from both policies
    baseline_actions = set()
    target_actions = set()

    for stmt in baseline_policy.get('Statement', []):
        actions = stmt.get('Action', [])
        if isinstance(actions, str):
            actions = [actions]
        baseline_actions.update(actions)

    for stmt in target_policy.get('Statement', []):
        actions = stmt.get('Action', [])
        if isinstance(actions, str):
            actions = [actions]
        target_actions.update(actions)

    # Find differences
    added = sorted(target_actions - baseline_actions)
    removed = sorted(baseline_actions - target_actions)

    return {
        'actions': {
            'baseline_only': removed,
            'target_only': added,
            'common': sorted(baseline_actions & target_actions)
        }
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze GCP WIF policy gaps between two OpenShift versions.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect versions (stable → candidate)
  %(prog)s

  # Explicit versions
  %(prog)s --baseline 4.21 --target 4.22

  # With verbose output
  %(prog)s --baseline 4.21 --target 4.22 --verbose

Exit Codes:
  0 - Successful execution (regardless of whether differences were found)
  1 - Execution failure (e.g., missing tools, network errors, invalid versions)
        """
    )

    parser.add_argument('--baseline', help='Baseline version (default: auto-detect from latest stable)')
    parser.add_argument('--target', help='Target version (default: auto-detect from latest candidate)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--report-dir',
                       default=os.environ.get('REPORT_DIR', 'reports'),
                       help='Directory to store reports (default: reports/, env: REPORT_DIR)')

    args = parser.parse_args()

    # Resolve versions using shared logic
    baseline = resolve_baseline_version(
        cli_arg=args.baseline,
        env_var=os.environ.get('BASE_VERSION')
    )
    target = resolve_target_version(
        cli_arg=args.target,
        env_var=os.environ.get('TARGET_VERSION')
    )

    # Main execution
    log_info("Starting GCP WIF Policy Gap Analysis")
    log_info("=========================================")
    log_info(f"Baseline version: {baseline}")
    log_info(f"Target version: {target}")
    log_info("=========================================")

    # Check prerequisites
    check_command('oc')
    check_command('jq')

    # Fetch policies
    baseline_policy = get_wif_policy(baseline)
    target_policy = get_wif_policy(target)

    # Compare
    log_info("Comparing WIF policies...")
    comparison = compare_wif_policies(baseline_policy, target_policy)

    # Check for differences
    added_count = len(comparison['actions']['target_only'])
    removed_count = len(comparison['actions']['baseline_only'])
    total_changes = added_count + removed_count

    if total_changes == 0:
        log_success(f"No policy differences found between {baseline} and {target}")
    else:
        log_info(f"Policy differences detected: {added_count} added, {removed_count} removed")

    # Generate reports
    # Create report directory if it doesn't exist
    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_data = {
        'type': 'GCP WIF Policy Gap Analysis',
        'baseline': baseline,
        'target': target,
        'timestamp': datetime.now().isoformat(),
        'comparison': comparison,
        'summary': {
            'added': added_count,
            'removed': removed_count,
            'total_changes': total_changes
        }
    }

    # Always generate JSON report (needed for combined report)
    json_file = os.path.join(report_dir, f"gap-analysis-gcp-wif_{baseline}_to_{target}_{timestamp}.json")
    generate_json_report(report_data, json_file)
    log_info(f"JSON report generated: {json_file}")

    # Skip Markdown and HTML reports if GAP_FULL_REPORT is set (full report will include these)
    if os.environ.get('GAP_FULL_REPORT'):
        log_info("Skipping Markdown/HTML reports (full report will be generated)")
    else:
        # Generate Markdown report
        md_file = os.path.join(report_dir, f"gap-analysis-gcp-wif_{baseline}_to_{target}_{timestamp}.md")
        generate_markdown_report(report_data, md_file)
        log_info(f"Markdown report generated: {md_file}")

        # Generate HTML report
        html_file = os.path.join(report_dir, f"gap-analysis-gcp-wif_{baseline}_to_{target}_{timestamp}.html")
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    # Always exit 0 on successful completion
    sys.exit(0)


if __name__ == '__main__':
    main()
