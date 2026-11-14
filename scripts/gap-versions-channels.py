#!/usr/bin/env python3
"""Version and Channel Gap Analysis - Validate OCP version availability across release channels."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from common import log_info, log_success, log_error, log_warning, is_version_5x
from openshift_releases import resolve_gap_versions, extract_minor_version, fetch_sippy_ga_dates, is_ga_minor_version
from reporters import generate_html_report, generate_json_report, generate_status_report
from reporters import build_status_details, format_failure_message


GA_CHANNELS = ['stable', 'eus', 'fast', 'candidate']
PRE_GA_CHANNELS = ['candidate']

# Bounded, sanitized query provenance kept in the CHECK #6 artifacts so an empty
# channel list can be told apart from an upstream failure or a local filter drop.
# Only allowlisted fields are retained: the query shape built from already
# validated inputs, counts, an error *kind*, and version-shaped tokens. Raw
# stdout/stderr, headers, environment and any credential-bearing request data
# are never copied into the evidence (command stderr keeps flowing into the
# pre-existing `api_errors` list only, exactly as before).
# The allowlist is deliberately narrow and length-bounded on every component so a
# sampled token cannot carry an arbitrary payload: ASCII digits only (no Unicode
# decimals), at most 4/4/6 digits per component and a 24-character pre-release or
# build suffix.
EVIDENCE_SAMPLE_LIMIT = 5
EVIDENCE_TEXT_LIMIT = 120
VERSION_TOKEN_RE = re.compile(r'^[0-9]{1,4}\.[0-9]{1,4}(\.[0-9]{1,6})?([-+][0-9A-Za-z.+-]{1,24})?$')

# Query outcomes. Successful-but-empty upstream responses and locally filtered
# responses are distinct, which is the ambiguity these artifacts must resolve.
OUTCOME_OK_NONEMPTY = 'ok_nonempty'
OUTCOME_OK_EMPTY_UPSTREAM = 'ok_empty_upstream'
OUTCOME_OK_ALL_FILTERED = 'ok_all_filtered'
OUTCOME_ERROR = 'error'


def _bounded_text(value):
    """Cap a recorded query string so no evidence field can grow unbounded."""
    if not isinstance(value, str) or len(value) <= EVIDENCE_TEXT_LIMIT:
        return value
    return value[:EVIDENCE_TEXT_LIMIT] + '…'


def _new_attempt(source, query):
    """Create a provenance record for one CLI attempt, pre-marked as failed.

    The record fails closed: callers promote it with _record_attempt_filtering()
    only once the CLI has actually answered.
    """
    return {
        'source': source,
        'query': {key: _bounded_text(value) for key, value in query.items()},
        'status': 'error',
        'error_kind': None,
        'upstream_item_count': 0,
        'matched_count': 0,
        'filtered_out_count': 0,
        'filtered_out_sample': [],
        'filtered_out_unparsable_count': 0,
    }


def _mark_attempt_error(attempt, error_kind):
    """Record a failed attempt by error kind only (never the raw CLI output)."""
    attempt['status'] = 'error'
    attempt['error_kind'] = error_kind
    return attempt


def _input_error_attempt(check, error_kind):
    """Provenance for a request rejected before any CLI was invoked."""
    return _mark_attempt_error(_new_attempt('input', {'check': check}), error_kind)


def _sanitize_version_tokens(values):
    """Allowlist version-shaped tokens for artifact evidence.

    Returns (sample, unparsable_count). Only tokens matching a strict version
    pattern are retained, de-duplicated so one repeated value cannot consume the
    whole budget, and capped at EVIDENCE_SAMPLE_LIMIT; anything else is counted
    but never echoed into the artifact.
    """
    sample = []
    unparsable = 0
    for value in values:
        token = value.strip() if isinstance(value, str) else ''
        if VERSION_TOKEN_RE.match(token):
            if len(sample) < EVIDENCE_SAMPLE_LIMIT and token not in sample:
                sample.append(token)
        else:
            unparsable += 1
    return sample, unparsable


def _record_attempt_filtering(attempt, upstream_ids, matched):
    """Record upstream-versus-filtered counts for a successful attempt."""
    attempt['status'] = 'ok'
    attempt['error_kind'] = None
    attempt['upstream_item_count'] = len(upstream_ids)
    attempt['matched_count'] = len(matched)
    matched_set = set(matched)
    filtered_out = [raw_id for raw_id in upstream_ids if raw_id not in matched_set]
    attempt['filtered_out_count'] = len(filtered_out)
    sample, unparsable = _sanitize_version_tokens(filtered_out)
    attempt['filtered_out_sample'] = sample
    attempt['filtered_out_unparsable_count'] = unparsable
    return attempt


def _attempt_outcome(attempt):
    """Classify a successful attempt: data, empty upstream, or filtered locally."""
    if attempt['matched_count'] > 0:
        return OUTCOME_OK_NONEMPTY
    if attempt['upstream_item_count'] > 0:
        return OUTCOME_OK_ALL_FILTERED
    return OUTCOME_OK_EMPTY_UPSTREAM


def _fetch_channel_via_ocm(minor_version, channel_group):
    """Fetch versions from OCM CLI for a minor version and channel group.

    Returns (versions_list, error, attempt) tuple, where attempt is the bounded
    sanitized provenance record for this call.
    """
    search = f"raw_id like '{minor_version}%' and channel_group='{channel_group}'"
    attempt = _new_attempt('ocm', {
        'command': 'ocm get',
        'endpoint': '/api/clusters_mgmt/v1/versions',
        'search': search,
        'size': 200,
        'order': 'raw_id asc',
        'local_filter': f"raw_id startswith '{minor_version}.'",
    })
    try:
        result = subprocess.run(
            ['ocm', 'get', '/api/clusters_mgmt/v1/versions',
             '--parameter', f'search={search}',
             '--parameter', 'size=200',
             '--parameter', 'order=raw_id asc'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30
        )
        if result.returncode != 0:
            err_msg = result.stderr.strip() if result.stderr else f"exit code {result.returncode}"
            _mark_attempt_error(attempt, 'exit_code')
            return [], f"ocm versions query for {channel_group}-{minor_version}: {err_msg}", attempt
        data = json.loads(result.stdout)
        items = data.get('items', [])
        raw_ids = [v.get('raw_id', '') for v in items]
        versions = sorted([raw_id for raw_id in raw_ids
                           if raw_id.startswith(f"{minor_version}.")])
        _record_attempt_filtering(attempt, raw_ids, versions)
        return versions, None, attempt
    except FileNotFoundError:
        return [], "ocm CLI not found", _mark_attempt_error(attempt, 'cli_not_found')
    except subprocess.TimeoutExpired:
        return ([], f"ocm versions query for {channel_group}-{minor_version}: timeout",
                _mark_attempt_error(attempt, 'timeout'))
    except json.JSONDecodeError as e:
        return ([], f"ocm versions query for {channel_group}-{minor_version}: {e}",
                _mark_attempt_error(attempt, 'invalid_json'))


def _fetch_channel_via_rosa(minor_version, channel_group):
    """Fetch versions from ROSA CLI for a minor version and channel group.

    Returns (versions_list, error, attempt) tuple. Parses text output from
    'rosa list versions --channel-group <group>'.
    """
    attempt = _new_attempt('rosa', {
        'command': 'rosa list versions',
        'channel_group': channel_group,
        'local_filter': f"version startswith '{minor_version}.'",
    })
    try:
        result = subprocess.run(
            ['rosa', 'list', 'versions', '--channel-group', channel_group],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30
        )
        if result.returncode != 0:
            err_msg = result.stderr.strip() if result.stderr else f"exit code {result.returncode}"
            _mark_attempt_error(attempt, 'exit_code')
            return [], f"rosa versions query for {channel_group}-{minor_version}: {err_msg}", attempt
        # upstream_item_count is source-relative: the ROSA output is plain text, so
        # only version-shaped rows can be counted. Header and prose lines are not
        # countable here, unlike the OCM item list which is counted in full.
        listed = []
        versions = []
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if parts and re.match(r'^\d+\.\d+\.', parts[0]):
                listed.append(parts[0])
                if parts[0].startswith(f"{minor_version}."):
                    versions.append(parts[0])
        versions = sorted(versions)
        _record_attempt_filtering(attempt, listed, versions)
        return versions, None, attempt
    except FileNotFoundError:
        return [], "rosa CLI not found", _mark_attempt_error(attempt, 'cli_not_found')
    except subprocess.TimeoutExpired:
        return ([], f"rosa versions query for {channel_group}-{minor_version}: timeout",
                _mark_attempt_error(attempt, 'timeout'))


def fetch_ocm_channel_data_with_evidence(minor_version, channel_group):
    """Fetch channel versions and the bounded provenance of how they were obtained.

    Same source order, inputs and retry policy as fetch_ocm_channel_data: OCM CLI
    first (structured JSON), ROSA CLI only as an error fallback. Returns
    (versions_list, error, evidence) where evidence records which source answered,
    whether the fallback ran, and upstream-versus-filtered counts.
    """
    evidence = {
        'source': 'none',
        'fallback_used': False,
        'outcome': OUTCOME_ERROR,
        'attempts': [],
    }

    if not re.match(r'^\d+\.\d+$', minor_version):
        evidence['attempts'].append(
            _input_error_attempt('minor_version_format', 'invalid_minor_version'))
        return [], f"Invalid minor version format: {minor_version}", evidence
    if not re.match(r'^[a-z]+$', channel_group):
        evidence['attempts'].append(
            _input_error_attempt('channel_group_format', 'invalid_channel_group'))
        return [], f"Invalid channel group format: {channel_group}", evidence

    versions, ocm_err, ocm_attempt = _fetch_channel_via_ocm(minor_version, channel_group)
    evidence['attempts'].append(ocm_attempt)
    if not ocm_err:
        evidence['source'] = 'ocm'
        evidence['outcome'] = _attempt_outcome(ocm_attempt)
        return versions, None, evidence

    log_warning(f"OCM CLI failed ({ocm_err}), falling back to ROSA CLI")
    evidence['fallback_used'] = True
    versions, rosa_err, rosa_attempt = _fetch_channel_via_rosa(minor_version, channel_group)
    evidence['attempts'].append(rosa_attempt)
    if not rosa_err:
        evidence['source'] = 'rosa'
        evidence['outcome'] = _attempt_outcome(rosa_attempt)
        return versions, None, evidence

    return [], f"{ocm_err}; rosa fallback also failed: {rosa_err}", evidence


def fetch_ocm_channel_data(minor_version, channel_group):
    """Fetch versions for a minor version and channel group via OCM or ROSA CLI.

    Tries OCM CLI first (structured JSON). Falls back to ROSA CLI (text parsing)
    if OCM is unavailable. Returns (versions_list, error) tuple. Callers that also
    need query provenance use fetch_ocm_channel_data_with_evidence().
    """
    versions, err, _evidence = fetch_ocm_channel_data_with_evidence(minor_version, channel_group)
    return versions, err


def summarize_channel_query_evidence(channel_analysis):
    """Aggregate per-channel query provenance into bounded report counters."""
    summary = {
        'queries': 0,
        OUTCOME_OK_NONEMPTY: 0,
        OUTCOME_OK_EMPTY_UPSTREAM: 0,
        OUTCOME_OK_ALL_FILTERED: 0,
        'errors': 0,
        'fallback_used': 0,
        'sources': {'ocm': 0, 'rosa': 0, 'none': 0},
    }
    for role in ('baseline', 'target'):
        channels = channel_analysis.get(role, {}).get('channels', {})
        for channel_info in channels.values():
            evidence = channel_info.get('query_evidence')
            if not evidence:
                continue
            summary['queries'] += 1
            outcome = evidence.get('outcome', OUTCOME_ERROR)
            # Explicit mapping: an unknown outcome counts as an error rather than
            # colliding with an unrelated counter such as 'queries' or 'sources'.
            if outcome in (OUTCOME_OK_NONEMPTY, OUTCOME_OK_EMPTY_UPSTREAM, OUTCOME_OK_ALL_FILTERED):
                summary[outcome] += 1
            else:
                summary['errors'] += 1
            if evidence.get('fallback_used'):
                summary['fallback_used'] += 1
            # Unknown sources fall back to 'none' so sum(sources) == queries holds.
            source = evidence.get('source', 'none')
            summary['sources'][source if source in summary['sources'] else 'none'] += 1
    return summary



def analyze_channel_availability(baseline_minor, target_minor, baseline_full, target_full,
                                  baseline_channels=None, target_channels=None):
    """Analyze which channels contain baseline and target versions."""
    if baseline_channels is None:
        baseline_channels = GA_CHANNELS
    if target_channels is None:
        target_channels = GA_CHANNELS

    result = {
        'baseline': {
            'version': baseline_full,
            'minor': baseline_minor,
            'channels': {}
        },
        'target': {
            'version': target_full,
            'minor': target_minor,
            'channels': {}
        },
        'baseline_version_channels': [],
        'target_version_channels': [],
        'baseline_in_stable': False,
        'target_highest_channel': 'none',
        'api_errors': [],
        'query_evidence_summary': {}
    }

    for channel_type in baseline_channels:
        log_info(f"Querying OCM versions: {channel_type}-{baseline_minor}")
        versions, err, evidence = fetch_ocm_channel_data_with_evidence(baseline_minor, channel_type)
        if err:
            result['api_errors'].append(err)
        channel_info = {
            'available': len(versions) > 0,
            'version_count': len(versions),
            'versions': versions,
            'latest': versions[-1] if versions else None,
            'query_evidence': evidence
        }
        result['baseline']['channels'][channel_type] = channel_info
        if len(versions) > 0:
            result['baseline_version_channels'].append(channel_type)

    for channel_type in target_channels:
        log_info(f"Querying OCM versions: {channel_type}-{target_minor}")
        versions, err, evidence = fetch_ocm_channel_data_with_evidence(target_minor, channel_type)
        if err:
            result['api_errors'].append(err)
        channel_info = {
            'available': len(versions) > 0,
            'version_count': len(versions),
            'versions': versions,
            'latest': versions[-1] if versions else None,
            'query_evidence': evidence
        }
        result['target']['channels'][channel_type] = channel_info
        if len(versions) > 0:
            result['target_version_channels'].append(channel_type)

    result['query_evidence_summary'] = summarize_channel_query_evidence(result)
    result['baseline_in_stable'] = 'stable' in result['baseline_version_channels']

    for ch in ['stable', 'fast', 'candidate']:
        if ch in result['target_version_channels']:
            result['target_highest_channel'] = ch
            break

    return result


def is_ocm_authenticated():
    """Check if ocm CLI is available and authenticated."""
    try:
        result = subprocess.run(
            ['ocm', 'whoami'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def fetch_ocm_versions(minor_version, channel_group='stable'):
    """Fetch versions from OCM API for a minor version and channel group."""
    if not re.match(r'^\d+\.\d+$', minor_version):
        log_warning(f"Invalid minor version format: {minor_version}")
        return []
    if not re.match(r'^[a-z]+$', channel_group):
        log_warning(f"Invalid channel group format: {channel_group}")
        return []
    try:
        search = f"raw_id like '{minor_version}%' and channel_group='{channel_group}'"
        result = subprocess.run(
            ['ocm', 'get', '/api/clusters_mgmt/v1/versions',
             '--parameter', f'search={search}',
             '--parameter', 'size=100',
             '--parameter', 'order=raw_id desc'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return data.get('items', [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        log_warning(f"Failed to fetch OCM versions for {minor_version} ({channel_group}): {e}")
        return []


def fetch_rosa_hcp_versions(minor_version, channel_group='candidate'):
    """Fetch HCP-enabled versions from ROSA CLI for a minor version and channel group."""
    try:
        result = subprocess.run(
            ['rosa', 'list', 'versions', '--hosted-cp', '--channel-group', channel_group],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30
        )
        if result.returncode != 0:
            return [], f"rosa HCP versions query for {channel_group}-{minor_version}: exit code {result.returncode}"
        versions = []
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if parts and re.match(r'^\d+\.\d+\.', parts[0]) and parts[0].startswith(f"{minor_version}."):
                versions.append(parts[0])
        return sorted(versions), None
    except FileNotFoundError:
        return [], "rosa CLI not found"
    except subprocess.TimeoutExpired:
        return [], f"rosa HCP versions query for {channel_group}-{minor_version}: timeout"


def analyze_marketplace_availability(baseline_minor, target_minor, baseline_full, target_full,
                                      skip_gcp_baseline=False, skip_gcp_target=False,
                                      baseline_channels=None, target_channels=None):
    """Check version availability on ROSA Classic, ROSA HCP, and OSD GCP marketplaces.

    Uses the same GA-aware channel sets as channel availability checks:
    GA versions check all channels, pre-GA versions check candidate only.
    OSD GCP skip is per-version: a 4.x baseline gets GCP checked even if target is 5.x.
    """
    if baseline_channels is None:
        baseline_channels = GA_CHANNELS
    if target_channels is None:
        target_channels = GA_CHANNELS

    result = {
        'available': False,
        'aws': {
            'baseline': {'version': baseline_full, 'rosa_enabled': None, 'channel_group': None},
            'target': {'version': target_full, 'rosa_enabled': None, 'channel_group': None},
            'target_minor_versions': []
        },
        'hcp': {
            'baseline': {'version': baseline_full, 'hcp_enabled': False, 'channels': []},
            'target': {'version': target_full, 'hcp_enabled': False, 'channels': []},
        },
        'gcp': {
            'baseline': {'version': baseline_full, 'gcp_marketplace_enabled': None, 'channel_group': None, 'skipped': skip_gcp_baseline},
            'target': {'version': target_full, 'gcp_marketplace_enabled': None, 'channel_group': None, 'skipped': skip_gcp_target},
            'target_minor_versions': [],
        }
    }

    # ROSA HCP check via ROSA CLI (doesn't require OCM auth)
    log_info("Checking ROSA HCP availability via ROSA CLI...")
    for channel_group in target_channels:
        log_info(f"  Querying ROSA HCP versions: {channel_group}-{target_minor}")
        versions, err = fetch_rosa_hcp_versions(target_minor, channel_group)
        if err:
            log_warning(f"  HCP check failed: {err}")
            continue
        if versions:
            result['hcp']['target']['channels'].append(channel_group)
            result['hcp']['target']['hcp_enabled'] = True

    for channel_group in baseline_channels:
        log_info(f"  Querying ROSA HCP versions: {channel_group}-{baseline_minor}")
        versions, err = fetch_rosa_hcp_versions(baseline_minor, channel_group)
        if err:
            continue
        if versions:
            result['hcp']['baseline']['channels'].append(channel_group)
            result['hcp']['baseline']['hcp_enabled'] = True
            break

    # ROSA Classic and OSD GCP checks via OCM API
    if not is_ocm_authenticated():
        log_warning("OCM not authenticated — skipping ROSA Classic and OSD GCP marketplace validation")
        log_warning("  Run 'ocm login --token=<token>' to enable marketplace checks")
        return result

    result['available'] = True
    log_info("OCM authenticated — checking ROSA Classic and OSD GCP marketplace availability")

    for channel_group in target_channels:
        versions = fetch_ocm_versions(target_minor, channel_group)
        for v in versions:
            raw_id = v.get('id', '').replace('openshift-v', '')
            version_info = {
                'version': raw_id,
                'channel_group': channel_group,
                'rosa_enabled': v.get('rosa_enabled', False),
                'gcp_marketplace_enabled': v.get('gcp_marketplace_enabled', False),
                'hosted_control_plane_enabled': v.get('hosted_control_plane_enabled', False),
                'enabled': v.get('enabled', False)
            }

            result['aws']['target_minor_versions'].append(version_info)
            if not skip_gcp_target:
                result['gcp']['target_minor_versions'].append(version_info)

            if raw_id == target_full or raw_id == f"{target_full}-{channel_group}":
                result['aws']['target']['rosa_enabled'] = v.get('rosa_enabled', False)
                result['aws']['target']['channel_group'] = channel_group
                if not skip_gcp_target:
                    result['gcp']['target']['gcp_marketplace_enabled'] = v.get('gcp_marketplace_enabled', False)
                    result['gcp']['target']['channel_group'] = channel_group

    for channel_group in baseline_channels:
        versions = fetch_ocm_versions(baseline_minor, channel_group)
        for v in versions:
            raw_id = v.get('id', '').replace('openshift-v', '')
            if raw_id == baseline_full or raw_id == f"{baseline_full}-{channel_group}":
                result['aws']['baseline']['rosa_enabled'] = v.get('rosa_enabled', False)
                result['aws']['baseline']['channel_group'] = channel_group
                if not skip_gcp_baseline:
                    result['gcp']['baseline']['gcp_marketplace_enabled'] = v.get('gcp_marketplace_enabled', False)
                    result['gcp']['baseline']['channel_group'] = channel_group
                break
        if result['aws']['baseline']['rosa_enabled'] is not None:
            break

    # Fallback: if exact baseline version not found, check any version for that minor
    if result['aws']['baseline']['rosa_enabled'] is None:
        for channel_group in baseline_channels:
            versions = fetch_ocm_versions(baseline_minor, channel_group)
            for v in versions:
                if v.get('rosa_enabled', False):
                    raw_id = v.get('id', '').replace('openshift-v', '')
                    result['aws']['baseline']['rosa_enabled'] = True
                    result['aws']['baseline']['channel_group'] = channel_group
                    result['aws']['baseline']['version'] = raw_id
                    if not skip_gcp_baseline and v.get('gcp_marketplace_enabled', False):
                        result['gcp']['baseline']['gcp_marketplace_enabled'] = True
                        result['gcp']['baseline']['channel_group'] = channel_group
                        result['gcp']['baseline']['version'] = raw_id
                    break
            if result['aws']['baseline']['rosa_enabled'] is not None:
                break

    return result


def _print_version_block(role, full_ver, minor_ver, channel_analysis, marketplace_analysis, verbose):
    """Print a single version block with channels and marketplace status."""
    role_key = role.lower()
    ch_data = channel_analysis[role_key]
    version_channels = channel_analysis[f'{role_key}_version_channels']
    skip_gcp = marketplace_analysis and marketplace_analysis['gcp'][role_key].get('skipped', False) if marketplace_analysis else False
    ocm_available = marketplace_analysis and marketplace_analysis.get('available', False)

    log_info(f"┌─ {role}: {full_ver}")

    if version_channels:
        ch_parts = []
        for ch in version_channels:
            ch_info = ch_data['channels'].get(ch, {})
            if verbose and ch_info.get('version_count'):
                ch_parts.append(f"✓ {ch} ({ch_info['version_count']}v, latest: {ch_info['latest']})")
            else:
                ch_parts.append(f"✓ {ch}")
        log_info(f"│  Channels:      {', '.join(ch_parts)}")
    else:
        log_warning(f"│  Channels:      ✗ not found in any {minor_ver} channel")

    if verbose:
        for ch_type, ch_info in ch_data['channels'].items():
            if ch_type not in version_channels:
                if ch_info.get('available'):
                    log_info(f"│    └ {ch_type}-{minor_ver}: {ch_info['version_count']} versions (but {full_ver} not present)")
                else:
                    log_info(f"│    └ {ch_type}-{minor_ver}: not available")

    if marketplace_analysis:
        hcp = marketplace_analysis['hcp'][role_key]
        if hcp['hcp_enabled']:
            log_info(f"│  ROSA HCP:      ✓ available ({', '.join(hcp['channels'])})")
        else:
            log_info(f"│  ROSA HCP:      ✗ not available")

        if ocm_available:
            aws = marketplace_analysis['aws'][role_key]
            if aws['rosa_enabled'] is None:
                log_info(f"│  ROSA Classic:  - not found in OCM")
            elif aws['rosa_enabled']:
                matched_ver = aws.get('version', full_ver)
                suffix = f" (via {matched_ver})" if matched_ver != full_ver else ""
                log_info(f"│  ROSA Classic:  ✓ enabled{suffix}")
            else:
                log_info(f"│  ROSA Classic:  ✗ disabled")

            if skip_gcp:
                log_info(f"│  OSD GCP:       ⊘ skipped (5.x AWS/STS-only)")
            else:
                gcp = marketplace_analysis['gcp'][role_key]
                if gcp['gcp_marketplace_enabled'] is None:
                    log_info(f"│  OSD GCP:       - not found in OCM")
                elif gcp['gcp_marketplace_enabled']:
                    log_info(f"│  OSD GCP:       ✓ enabled")
                else:
                    log_info(f"│  OSD GCP:       ✗ disabled")
        else:
            log_info(f"│  ROSA Classic:  — OCM not authenticated")
            if skip_gcp:
                log_info(f"│  OSD GCP:       ⊘ skipped (5.x AWS/STS-only)")
            else:
                log_info(f"│  OSD GCP:       — OCM not authenticated")

    log_info(f"└──────────────────────────────────────────")


def print_analysis(channel_analysis,
                   baseline_full, target_full, verbose=False, marketplace_analysis=None):
    """Print analysis results organized by version."""
    baseline_minor = channel_analysis['baseline']['minor']
    target_minor = channel_analysis['target']['minor']

    log_info("\nCHECK #6: Versions & Channels Analysis")
    log_info("")

    _print_version_block('Baseline', baseline_full, baseline_minor,
                         channel_analysis, marketplace_analysis, verbose)
    log_info("")
    _print_version_block('Target', target_full, target_minor,
                         channel_analysis, marketplace_analysis, verbose)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze OCP version availability across release channels.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect versions (stable → candidate)
  %(prog)s

  # Single version (auto-resolves baseline and target)
  %(prog)s --version 4.22

  # Explicit versions
  %(prog)s --baseline 4.21 --target 4.22

  # With verbose output
  %(prog)s --baseline 4.21 --target 4.22 --verbose

Exit Codes:
  0 - Successful execution (regardless of findings)
  1 - Execution failure (e.g., network errors, invalid versions)
        """
    )

    parser.add_argument('--version', help='Single version to analyze (auto-resolves baseline and target)')
    parser.add_argument('--baseline', help='Baseline version (requires --target)')
    parser.add_argument('--target', help='Target version (requires --baseline)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--report-dir',
                       default=os.environ.get('REPORT_DIR', 'reports'),
                       help='Directory to store reports (default: reports/, env: REPORT_DIR)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show versions that would be used and exit (no analysis performed)')

    args = parser.parse_args()

    # Resolve versions using shared logic
    baseline_full, target_full = resolve_gap_versions(
        version=args.version, baseline=args.baseline, target=args.target
    )

    baseline_minor = extract_minor_version(baseline_full)
    target_minor = extract_minor_version(target_full)
    is_z_stream = (baseline_minor == target_minor)

    # Main execution
    log_info("Starting Version & Channel Gap Analysis")
    log_info("=========================================")
    log_info(f"Baseline version: {baseline_full} (minor: {baseline_minor})")
    log_info(f"Target version: {target_full} (minor: {target_minor})")
    if is_z_stream:
        log_info(f"Comparison type: Z-stream (same minor version)")
    else:
        log_info(f"Comparison type: Cross-minor ({baseline_minor} → {target_minor})")
    log_info("=========================================")

    if args.dry_run:
        log_info("")
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    # Determine GA status and 5.x platform constraints
    ga_dates = fetch_sippy_ga_dates()
    baseline_is_ga = is_ga_minor_version(baseline_minor, ga_dates)
    target_is_ga = is_ga_minor_version(target_minor, ga_dates)
    baseline_channels = GA_CHANNELS if baseline_is_ga else PRE_GA_CHANNELS
    target_channels = GA_CHANNELS if target_is_ga else PRE_GA_CHANNELS
    skip_gcp_baseline = is_version_5x(baseline_minor)
    skip_gcp_target = is_version_5x(target_minor)

    log_info(f"Baseline {baseline_minor} GA status: {'GA' if baseline_is_ga else 'pre-GA'} → channels: {baseline_channels}")
    log_info(f"Target {target_minor} GA status: {'GA' if target_is_ga else 'pre-GA'} → channels: {target_channels}")
    if skip_gcp_baseline:
        log_info(f"Baseline {baseline_minor} is 5.x — OSD GCP skipped (AWS/STS-only)")
    if skip_gcp_target:
        log_info(f"Target {target_minor} is 5.x — OSD GCP skipped (AWS/STS-only)")

    # Run analyses
    log_info("\nAnalyzing channel availability...")
    channel_analysis = analyze_channel_availability(
        baseline_minor, target_minor, baseline_full, target_full,
        baseline_channels=baseline_channels, target_channels=target_channels
    )

    log_info("\nChecking marketplace availability...")
    marketplace_analysis = analyze_marketplace_availability(
        baseline_minor, target_minor, baseline_full, target_full,
        skip_gcp_baseline=skip_gcp_baseline, skip_gcp_target=skip_gcp_target,
        baseline_channels=baseline_channels, target_channels=target_channels
    )

    # Print results
    print_analysis(
        channel_analysis,
        baseline_full, target_full, args.verbose, marketplace_analysis
    )

    # Generate reports
    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Collect API errors from all analyses
    api_errors = []
    for analysis in [channel_analysis]:
        api_errors.extend(analysis.get('api_errors', []))

    if api_errors:
        log_warning(f"{len(api_errors)} OCM API call(s) failed — results may be incomplete:")
        for err in api_errors:
            log_warning(f"  - {err}")

    # Determine validation result based on channel availability and marketplace
    validation_result = 'PASS'
    validation_errors = []
    target_in_channel = len(channel_analysis['target_version_channels']) > 0

    if not target_in_channel and target_is_ga:
        validation_result = 'FAIL'
        validation_errors.append(
            f"Target {target_full} not found in any {target_minor} channel "
            "(next version after GA — must be available)"
        )
        log_error(validation_errors[-1])
    elif not target_in_channel:
        log_warning(f"Target {target_full} not found in any {target_minor} channel (dev version — informational only)")

    # Marketplace validation for GA targets:
    #   ROSA HCP:     missing → FAIL (mandatory, all versions)
    #   ROSA Classic: missing → FAIL (4.x), WARN (5.x)
    #   OSD GCP:      missing → FAIL (4.x only, skipped for 5.x)
    if target_is_ga:
        if not marketplace_analysis['hcp']['target']['hcp_enabled']:
            validation_result = 'FAIL'
            validation_errors.append(f"Target {target_minor} not available for ROSA HCP (mandatory for GA)")
            log_error(validation_errors[-1])

        if marketplace_analysis.get('available'):
            aws_enabled = marketplace_analysis['aws']['target']['rosa_enabled']
            if not aws_enabled:
                if skip_gcp_target:
                    log_warning(f"Target {target_full} not enabled for ROSA Classic")
                else:
                    validation_result = 'FAIL'
                    validation_errors.append(
                        f"Target {target_full} not enabled for ROSA Classic (mandatory for GA 4.x)"
                    )
                    log_error(validation_errors[-1])

            if not skip_gcp_target:
                gcp_enabled = marketplace_analysis['gcp']['target']['gcp_marketplace_enabled']
                if not gcp_enabled:
                    validation_result = 'FAIL'
                    validation_errors.append(
                        f"Target {target_full} not enabled for OSD GCP (mandatory for GA 4.x)"
                    )
                    log_error(validation_errors[-1])
        else:
            log_warning("OCM not authenticated — cannot validate ROSA Classic and OSD GCP marketplace for GA version")

    report_data = {
        'type': 'Version Channel Gap Analysis',
        'baseline': baseline_full,
        'target': target_full,
        'baseline_minor': baseline_minor,
        'target_minor': target_minor,
        'is_z_stream': is_z_stream,
        'timestamp': datetime.now().isoformat(),
        'validation_result': validation_result,
        'validation_errors': validation_errors,
        'channel_availability': channel_analysis,
        'marketplace': marketplace_analysis,
        'summary': {
            'baseline_in_stable': channel_analysis['baseline_in_stable'],
            'target_highest_channel': channel_analysis['target_highest_channel'],
            'baseline_channels': channel_analysis['baseline_version_channels'],
            'target_channels': channel_analysis['target_version_channels'],
            'target_is_ga': target_is_ga,
            'marketplace_available': marketplace_analysis.get('available', False),
            'target_rosa_classic': marketplace_analysis['aws']['target']['rosa_enabled'] if marketplace_analysis.get('available') else None,
            'target_rosa_hcp': marketplace_analysis['hcp']['target']['hcp_enabled'],
            'target_osd_gcp': marketplace_analysis['gcp']['target']['gcp_marketplace_enabled'] if marketplace_analysis.get('available') and not skip_gcp_target else None,
            'gcp_skipped': skip_gcp_target,
            'api_errors': api_errors,
            'channel_query_evidence': channel_analysis.get('query_evidence_summary', {}),
        }
    }

    # Always generate JSON report
    json_file = os.path.join(
        report_dir,
        f"gap-analysis-versions-channels_{baseline_minor}_to_{target_minor}_{timestamp}.json"
    )
    generate_json_report(report_data, json_file)
    log_info(f"\nJSON report generated: {json_file}")

    # Skip HTML if full report mode
    if os.environ.get('GAP_FULL_REPORT'):
        log_info("Skipping HTML reports (full report will be generated)")
    else:
        html_file = os.path.join(
            report_dir,
            f"gap-analysis-versions-channels_{baseline_minor}_to_{target_minor}_{timestamp}.html"
        )
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    log_fn = log_success if validation_result == 'PASS' else log_error

    log_fn("=" * 60)
    if validation_result == 'PASS':
        log_fn("✓ VALIDATION PASSED - Versions & Channels")
    else:
        log_fn("✗ VALIDATION FAILED - Versions & Channels")
    log_fn("=" * 60)
    log_fn(f"\nCHECK #6: Versions & Channels Analysis [{validation_result}]")
    log_fn(f"  Data Sources: OCM CLI, ROSA CLI, Sippy")

    if is_z_stream:
        log_fn(f"  Comparison Type: Z-stream ({baseline_full} → {target_full})")
    else:
        log_fn(f"  Comparison Type: Cross-minor ({baseline_minor} → {target_minor})")

    if channel_analysis['baseline_in_stable']:
        log_fn(f"  ✓ Baseline {baseline_full} is in stable channel")
    else:
        log_fn(f"  ℹ️  Baseline {baseline_full} not in stable (channels: {', '.join(channel_analysis['baseline_version_channels']) or 'none'})")

    if target_in_channel:
        log_fn(f"  ✓ Target {target_full} highest channel: {channel_analysis['target_highest_channel']}")
    else:
        log_fn(f"  ✗ Target {target_full} not found in any {target_minor} channel")

    hcp_status = marketplace_analysis['hcp']['target']['hcp_enabled']
    log_fn(f"  {'✓' if hcp_status else '✗'} ROSA HCP: {'available' if hcp_status else 'NOT available'}")

    if marketplace_analysis.get('available'):
        aws_status = marketplace_analysis['aws']['target']['rosa_enabled']
        if aws_status is not None:
            log_fn(f"  {'✓' if aws_status else '✗'} ROSA Classic: {'available' if aws_status else 'NOT available'}")
        if not skip_gcp_target:
            gcp_status = marketplace_analysis['gcp']['target']['gcp_marketplace_enabled']
            if gcp_status is not None:
                log_fn(f"  {'✓' if gcp_status else '✗'} OSD GCP: {'available' if gcp_status else 'NOT available'}")
        else:
            log_fn(f"  ⊘ OSD GCP: skipped (5.x is AWS/STS-only)")

    log_fn("")
    if validation_result == 'PASS':
        log_fn(f"✅ PASSED - Version & Channel analysis complete")
    else:
        log_fn(f"❌ FAILED - Target version not available in any channel")

    # Generate status file for gap-all.sh
    if validation_result == 'FAIL':
        status_message = format_failure_message(
            f"{len(validation_errors) or 1} validation failure(s)",
            validation_errors,
        )
    else:
        status_message = f"target highest channel: {channel_analysis['target_highest_channel']}"

    status_details = build_status_details(
        status_message,
        validation_errors if validation_errors else None,
        is_z_stream=is_z_stream,
        baseline_in_stable=channel_analysis['baseline_in_stable'],
        target_highest_channel=channel_analysis['target_highest_channel'],
        marketplace_available=marketplace_analysis.get('available', False),
        gcp_skipped=skip_gcp_target,
        target_is_ga=target_is_ga,
    )

    generate_status_report(
        check_number=6,
        check_name="Versions & Channels",
        status=validation_result,
        details=status_details,
        report_dir=report_dir
    )

    sys.exit(1 if validation_result == 'FAIL' else 0)


if __name__ == '__main__':
    main()
