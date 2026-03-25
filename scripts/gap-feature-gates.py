#!/usr/bin/env python3
"""Feature Gate Gap Analysis - Compare feature gates between OpenShift versions."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info, log_success, log_error, check_command
from openshift_releases import resolve_baseline_version, resolve_target_version, extract_minor_version
from reporters import generate_markdown_report, generate_html_report, generate_json_report


SIPPY_FEATURE_GATES_API = "https://sippy.dptools.openshift.org/api/feature_gates"


def fetch_feature_gates(version):
    """Fetch feature gates for a specific version from Sippy API."""
    log_info(f"Fetching feature gates for version {version}...")

    try:
        url = f"{SIPPY_FEATURE_GATES_API}?release={version}"
        req = Request(url, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=30) as response:
            data = response.read()
            gates = json.loads(data)

        if not gates:
            log_error(f"No feature gates found for version {version}")
            sys.exit(1)

        log_success(f"Fetched {len(gates)} feature gates for version {version}")
        return gates

    except (URLError, json.JSONDecodeError) as e:
        log_error(f"Failed to fetch feature gates for version {version}: {e}")
        sys.exit(1)


def compare_feature_gates(baseline_data, target_data):
    """Compare feature gates between baseline and target versions."""
    # Extract feature gate names
    baseline_gates = {g['feature_gate'] for g in baseline_data}
    target_gates = {g['feature_gate'] for g in target_data}

    # Find differences
    added = sorted(target_gates - baseline_gates)
    removed = sorted(baseline_gates - target_gates)
    common = baseline_gates & target_gates

    # Create lookup dicts for common gates
    baseline_dict = {g['feature_gate']: g for g in baseline_data}
    target_dict = {g['feature_gate']: g for g in target_data}

    # Analyze default enablement changes
    newly_default = []
    removed_default = []

    for gate in common:
        baseline_enabled = baseline_dict[gate].get('enabled', [])
        target_enabled = target_dict[gate].get('enabled', [])

        baseline_has_default = any('Default:' in e for e in baseline_enabled)
        target_has_default = any('Default:' in e for e in target_enabled)

        if not baseline_has_default and target_has_default:
            newly_default.append(gate)
        elif baseline_has_default and not target_has_default:
            removed_default.append(gate)

    return {
        'added': sorted(added),
        'removed': sorted(removed),
        'newly_enabled_by_default': sorted(newly_default),
        'removed_from_default': sorted(removed_default)
    }


def print_comparison(comparison, baseline, target, verbose=False):
    """Print comparison results."""
    added_count = len(comparison['added'])
    removed_count = len(comparison['removed'])
    newly_default_count = len(comparison['newly_enabled_by_default'])
    removed_default_count = len(comparison['removed_from_default'])

    total_changes = added_count + removed_count + newly_default_count + removed_default_count

    if total_changes == 0:
        log_success(f"No feature gate differences found between {baseline} and {target}")
        return

    log_info("Feature gate differences detected:")
    if added_count > 0:
        log_info(f"  - New feature gates: {added_count}")
    if removed_count > 0:
        log_info(f"  - Removed feature gates: {removed_count}")
    if newly_default_count > 0:
        log_info(f"  - Newly enabled by default: {newly_default_count}")
    if removed_default_count > 0:
        log_info(f"  - Removed from default: {removed_default_count}")

    if verbose:
        if added_count > 0:
            log_info("")
            log_info(f"New feature gates in {target}:")
            for gate in comparison['added']:
                log_info(f"  + {gate}")

        if removed_count > 0:
            log_info("")
            log_info(f"Removed feature gates in {target}:")
            for gate in comparison['removed']:
                log_info(f"  - {gate}")

        if newly_default_count > 0:
            log_info("")
            log_info(f"Newly enabled by default in {target}:")
            for gate in comparison['newly_enabled_by_default']:
                log_info(f"  ✓ {gate}")

        if removed_default_count > 0:
            log_info("")
            log_info(f"Removed from default in {target}:")
            for gate in comparison['removed_from_default']:
                log_info(f"  ✗ {gate}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze feature gate differences between two OpenShift versions.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect versions (stable → candidate)
  %(prog)s

  # Explicit versions
  %(prog)s --baseline 4.21 --target 4.22

  # With verbose output
  %(prog)s --baseline 4.21 --target 4.22 --verbose

  # Environment variables
  BASE_VERSION=4.21 TARGET_VERSION=4.22 %(prog)s

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

    # Feature gates API needs minor version only (e.g., "4.21" not "4.21.7")
    baseline = extract_minor_version(baseline)
    target = extract_minor_version(target)

    # Main execution
    log_info("Starting Feature Gate Gap Analysis")
    log_info("=========================================")
    log_info(f"Baseline version: {baseline}")
    log_info(f"Target version: {target}")
    log_info("=========================================")

    # Check prerequisites
    check_command('curl')

    # Fetch feature gates
    baseline_data = fetch_feature_gates(baseline)
    target_data = fetch_feature_gates(target)

    # Compare
    log_info("Comparing feature gates...")
    comparison = compare_feature_gates(baseline_data, target_data)

    # Print results
    print_comparison(comparison, baseline, target, args.verbose)

    # Generate reports
    # Create report directory if it doesn't exist
    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    added_count = len(comparison['added'])
    removed_count = len(comparison['removed'])
    newly_default_count = len(comparison['newly_enabled_by_default'])
    removed_default_count = len(comparison['removed_from_default'])
    total_changes = added_count + removed_count + newly_default_count + removed_default_count

    report_data = {
        'type': 'Feature Gate Gap Analysis',
        'baseline': baseline,
        'target': target,
        'timestamp': datetime.now().isoformat(),
        'comparison': comparison,
        'summary': {
            'added': added_count,
            'removed': removed_count,
            'newly_enabled_by_default': newly_default_count,
            'removed_from_default': removed_default_count,
            'total_changes': total_changes
        }
    }

    # Always generate JSON report (needed for combined report)
    json_file = os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline}_to_{target}_{timestamp}.json")
    generate_json_report(report_data, json_file)
    log_info(f"JSON report generated: {json_file}")

    # Skip Markdown and HTML reports if GAP_FULL_REPORT is set (full report will include these)
    if os.environ.get('GAP_FULL_REPORT'):
        log_info("Skipping Markdown/HTML reports (full report will be generated)")
    else:
        # Generate Markdown report
        md_file = os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline}_to_{target}_{timestamp}.md")
        generate_markdown_report(report_data, md_file)
        log_info(f"Markdown report generated: {md_file}")

        # Generate HTML report
        html_file = os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline}_to_{target}_{timestamp}.html")
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    # Always exit 0 on successful completion
    sys.exit(0)


if __name__ == '__main__':
    import os
    main()
