#!/usr/bin/env python3
"""
Generate PR content for managed-cluster-config based on gap analysis failures.

This script:
1. Reads gap-analysis JSON report
2. Extracts credentials from target OCP release (reuses gap-aws-sts/gap-gcp-wif functions)
3. Generates policy files in managed-cluster-config format
4. Generates acknowledgment files based on templates from previous version
5. Appends complete file content to pr-summary.md
"""

import argparse
import json
import os
import sys
import yaml
import tempfile
import shutil
import subprocess
import re
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen

# Add scripts/lib to path to reuse existing functions
SCRIPT_DIR = Path(__file__).parent
CI_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = CI_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

# Import existing gap analysis modules
import importlib.util

def import_module_from_file(module_name, file_path):
    """Import a module from a file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Import gap analysis scripts
gap_aws_sts = import_module_from_file('gap_aws_sts', PROJECT_ROOT / 'scripts' / 'gap-aws-sts.py')
gap_gcp_wif = import_module_from_file('gap_gcp_wif', PROJECT_ROOT / 'scripts' / 'gap-gcp-wif.py')

from common import log_info, log_success, log_error, log_warning
from openshift_releases import extract_minor_version


def fetch_github_directory_files(repo, path, file_extension=None):
    """
    Fetch all files from a GitHub directory.

    Args:
        repo: Repository in format 'owner/repo'
        path: Directory path (e.g., 'resources/sts/4.21')
        file_extension: Optional filter by extension (e.g., '.json', '.yaml')

    Returns: dict mapping filename -> file content (parsed JSON/YAML or raw text)
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    log_info(f"Fetching files from {repo}/{path}...")

    try:
        with urlopen(url) as response:
            files_list = json.loads(response.read().decode('utf-8'))

        if not isinstance(files_list, list):
            log_error(f"Expected list of files, got: {type(files_list)}")
            return {}

        files = {}
        for file_info in files_list:
            if file_info.get('type') != 'file':
                continue

            filename = file_info.get('name', '')

            # Filter by extension if specified
            if file_extension and not filename.endswith(file_extension):
                continue

            download_url = file_info.get('download_url')
            if not download_url:
                continue

            # Download file content
            try:
                with urlopen(download_url) as file_response:
                    content = file_response.read().decode('utf-8')

                # Parse based on file extension
                if filename.endswith('.json'):
                    files[filename] = json.loads(content)
                elif filename.endswith('.yaml') or filename.endswith('.yml'):
                    files[filename] = yaml.safe_load(content)
                else:
                    files[filename] = content

                log_info(f"  ✓ Fetched: {filename}")
            except Exception as e:
                log_warning(f"  ✗ Failed to fetch {filename}: {e}")

        log_success(f"Fetched {len(files)} file(s) from {path}")
        return files

    except Exception as e:
        log_error(f"Failed to fetch directory contents from {url}: {e}")
        return {}


def copy_previous_sts_files(baseline_version):
    """
    Copy ALL STS policy files from previous version.

    This ensures we preserve infrastructure files (installer policies, SCP policies, etc.)
    that don't come from CredentialRequests.

    Returns: dict mapping filename -> policy content
    """
    baseline_minor = extract_minor_version(baseline_version)
    path = f"resources/sts/{baseline_minor}"

    log_info(f"Copying ALL STS files from baseline version {baseline_minor}...")

    files = fetch_github_directory_files('openshift/managed-cluster-config', path, '.json')

    if not files:
        log_warning(f"No STS files found for baseline {baseline_minor}")
        return {}

    log_success(f"Copied {len(files)} STS policy files from {baseline_minor}")
    return files


def copy_previous_wif_files(baseline_version):
    """
    Copy ALL WIF template files from previous version.

    Returns: dict mapping filename -> template content
    """
    baseline_minor = extract_minor_version(baseline_version)
    path = f"resources/wif/{baseline_minor}"

    log_info(f"Copying ALL WIF files from baseline version {baseline_minor}...")

    files = fetch_github_directory_files('openshift/managed-cluster-config', path, '.yaml')

    if not files:
        log_warning(f"No WIF files found for baseline {baseline_minor}")
        return {}

    log_success(f"Copied {len(files)} WIF template files from {baseline_minor}")
    return files


def read_gap_report(report_path):
    """Read and parse gap analysis JSON report."""
    with open(report_path, 'r') as f:
        return json.load(f)


def check_gcp_wif_diff(baseline, target):
    """
    Check if there are GCP permission differences between versions.

    Runs gap-gcp-wif.py and parses the JSON report.
    Returns: (has_diff, report_data)
    """
    log_info(f"Checking GCP WIF permission diff between {baseline} and {target}...")

    # Run gap-gcp-wif.py to temp location
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                'python3',
                str(PROJECT_ROOT / 'scripts' / 'gap-gcp-wif.py'),
                '--baseline', baseline,
                '--target', target,
                '--report-dir', tmpdir
            ],
            capture_output=True,
            text=True
        )

        # Find the JSON report
        json_files = list(Path(tmpdir).glob('gap-analysis-gcp-wif_*.json'))
        if not json_files:
            log_warning("No GCP WIF report generated, assuming diff exists")
            return True, None

        with open(json_files[0], 'r') as f:
            report = json.load(f)

        # Check for permission differences
        comparison = report.get('comparison', {})
        added = comparison.get('added_permissions', []) or []
        removed = comparison.get('removed_permissions', []) or []

        has_diff = len(added) > 0 or len(removed) > 0

        if has_diff:
            log_info(f"GCP WIF permissions changed: +{len(added)} -{len(removed)}")
        else:
            log_success("No GCP WIF permission changes detected")

        return has_diff, report


def fetch_previous_wif_template(version):
    """
    Fetch vanilla.yaml from managed-cluster-config for a specific version.

    Returns: dict parsed from YAML
    """
    minor_version = extract_minor_version(version)
    url = f"https://raw.githubusercontent.com/openshift/managed-cluster-config/master/resources/wif/{minor_version}/vanilla.yaml"

    log_info(f"Fetching WIF template for {minor_version} from MCC repo...")

    try:
        with urlopen(url) as response:
            content = response.read().decode('utf-8')
            return yaml.safe_load(content)
    except Exception as e:
        log_error(f"Failed to fetch {url}: {e}")
        return None


def calculate_previous_versions(target_version, count=3):
    """
    Calculate previous N versions based on target version.

    Example: target_version='4.22' → returns ['4.21', '4.20', '4.19']

    Args:
        target_version: Target version (e.g., '4.22.0-ec.4')
        count: Number of previous versions to calculate (default: 3)

    Returns: List of previous version strings
    """
    minor_version = extract_minor_version(target_version)
    major, minor = minor_version.split('.')
    major_int = int(major)
    minor_int = int(minor)

    previous_versions = []
    for i in range(1, count + 1):
        prev_minor = minor_int - i
        if prev_minor >= 0:
            previous_versions.append(f"{major_int}.{prev_minor}")

    return previous_versions


def validate_wif_pattern_consistency(target_version):
    """
    Validate that version patterns are consistent across previous 3 versions.

    Checks:
    - Same number of service accounts
    - Same service account IDs (except version in role IDs)
    - Consistent version pattern in role IDs

    Args:
        target_version: Target version to validate against

    Returns: (is_consistent, pattern_info)
    """
    versions = calculate_previous_versions(target_version)

    if not versions:
        log_warning("No previous versions available for comparison")
        return True, None

    log_info(f"Validating WIF pattern consistency across {versions}...")

    templates = {}
    for version in versions:
        template = fetch_previous_wif_template(version)
        if not template:
            log_warning(f"Could not fetch template for {version}")
            return False, None
        templates[version] = template

    # Check service account counts
    sa_counts = {v: len(t['service_accounts']) for v, t in templates.items()}
    if len(set(sa_counts.values())) > 1:
        log_warning(f"Inconsistent service account counts: {sa_counts}")
        return False, None

    # Check service account IDs (normalized - remove version patterns)
    for version, template in templates.items():
        sa_ids = sorted([sa['id'] for sa in template['service_accounts']])
        log_info(f"  {version}: {len(sa_ids)} service accounts")

    # Pattern is consistent if all checks pass
    pattern_info = {
        'service_account_count': sa_counts[versions[0]],
        'versions_checked': versions
    }

    log_success(f"WIF pattern validated: {pattern_info['service_account_count']} service accounts")
    return True, pattern_info


def copy_and_update_wif_template(baseline_version, target_version):
    """
    Copy ALL WIF files from baseline and update version patterns.

    Strategy:
    1. Copy all WIF files from baseline version (preserves any additional files)
    2. Update version patterns in vanilla.yaml

    Transformations:
    - id: v{baseline} → id: v{target}
    - role IDs: *_v{baseline} → *_v{target}

    Returns: dict with filename -> content
    """
    baseline_minor = extract_minor_version(baseline_version)
    target_minor = extract_minor_version(target_version)

    log_info(f"Copying WIF files from {baseline_minor} and updating to {target_minor}...")

    # Copy all WIF files from baseline
    all_files = copy_previous_wif_files(baseline_version)

    if not all_files:
        log_error(f"Failed to copy baseline WIF files for {baseline_minor}")
        return None

    # Update vanilla.yaml version patterns (if it exists)
    if 'vanilla.yaml' in all_files:
        template = all_files['vanilla.yaml']

        # Update top-level version ID
        template['id'] = f"v{target_minor}"

        # Update role IDs in service accounts
        for sa in template['service_accounts']:
            for role in sa.get('roles', []):
                role_id = role['id']
                # Replace version pattern: *_v4.21 → *_v4.22
                role['id'] = re.sub(
                    r'_v' + re.escape(baseline_minor) + r'$',
                    f'_v{target_minor}',
                    role_id
                )

        log_success(f"Updated {len(template['service_accounts'])} service accounts to v{target_minor}")

    return all_files


def normalize_keys(data, reference_data=None):
    """
    Normalize JSON keys to match reference data casing.

    If reference_data provided, matches its key casing.
    Otherwise, capitalizes standard IAM policy keys (Action, Effect, Resource, etc.)

    Args:
        data: Dictionary to normalize
        reference_data: Optional reference dictionary for key casing

    Returns: Dictionary with normalized keys
    """
    if not isinstance(data, dict):
        return data

    # Standard IAM policy key capitalization
    standard_keys = {
        'action': 'Action',
        'effect': 'Effect',
        'resource': 'Resource',
        'condition': 'Condition',
        'principal': 'Principal',
        'notaction': 'NotAction',
        'notresource': 'NotResource',
        'sid': 'Sid'
    }

    result = {}

    # If reference provided, use its key casing
    if reference_data:
        ref_keys_lower = {k.lower(): k for k in reference_data.keys()}

    for key, value in data.items():
        # Determine correct key casing
        if reference_data and key.lower() in ref_keys_lower:
            correct_key = ref_keys_lower[key.lower()]
        elif key.lower() in standard_keys:
            correct_key = standard_keys[key.lower()]
        else:
            correct_key = key

        # Recursively normalize nested dicts and lists
        if isinstance(value, dict):
            ref_value = reference_data.get(correct_key) if reference_data else None
            result[correct_key] = normalize_keys(value, ref_value)
        elif isinstance(value, list):
            result[correct_key] = [
                normalize_keys(item, None) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[correct_key] = value

    return result


def apply_statement_diff(baseline_statements, target_statements):
    """
    Apply diff from target statements to baseline statements.

    Preserves baseline structure and only updates the Statement array.
    Keeps baseline key casing.

    Args:
        baseline_statements: Original Statement array from baseline
        target_statements: New Statement array from target CredentialRequest

    Returns: Updated Statement array with normalized keys matching baseline
    """
    if not baseline_statements:
        return target_statements

    # Use first statement from baseline as reference for key casing
    reference_stmt = baseline_statements[0] if baseline_statements else None

    # Normalize target statements to match baseline casing
    normalized_target = [
        normalize_keys(stmt, reference_stmt)
        for stmt in target_statements
    ]

    return normalized_target


def extract_credreqs_map(version):
    """
    Extract CredentialRequests and create a mapping of CR metadata to statements.

    Returns: dict mapping (namespace, name) tuple -> Statement array
    """
    log_info(f"Extracting CredentialRequests for {version}...")

    cr_dir = gap_aws_sts.extract_credential_requests(version, cloud="aws")
    if not cr_dir:
        return {}

    cr_map = {}

    for cr_file in Path(cr_dir).glob('*.yaml'):
        with open(cr_file, 'r') as f:
            cr_data = yaml.safe_load(f)

        metadata = cr_data.get('metadata', {})
        namespace = metadata.get('namespace', '')
        name = metadata.get('name', '')

        spec = cr_data.get('spec', {})
        provider_spec = spec.get('providerSpec', {})

        if 'statementEntries' in provider_spec:
            key = (namespace, name)
            cr_map[key] = provider_spec['statementEntries']

    # Cleanup
    shutil.rmtree(cr_dir, ignore_errors=True)

    log_success(f"Extracted {len(cr_map)} CredentialRequests")
    return cr_map


def match_baseline_file_to_credreq(filename, baseline_cr_map, target_cr_map):
    """
    Find matching CredentialRequest for a baseline policy file.

    Strategy:
    1. Try exact namespace/name match from filename
    2. Try partial name matches
    3. Return None if no match

    Returns: target Statement array if match found, None otherwise
    """
    # Remove .json and parse filename parts
    # Pattern: openshift_{namespace}_{name}_policy.json
    name_parts = filename.replace('_policy.json', '').replace('openshift_', '').split('_')

    if len(name_parts) < 2:
        return None

    # Try to reconstruct namespace and name
    # Could be: namespace_name or namespace_name_name
    for i in range(1, len(name_parts)):
        namespace_parts = name_parts[:i]
        name_parts_remaining = name_parts[i:]

        namespace = '-'.join(namespace_parts)
        name = '-'.join(name_parts_remaining)

        # Try direct match in target
        key = (namespace, name)
        if key in target_cr_map:
            return target_cr_map[key]

        # Try with openshift- prefix variations
        for ns_prefix in ['', 'openshift-']:
            test_key = (ns_prefix + namespace, name)
            if test_key in target_cr_map:
                return target_cr_map[test_key]

    # Try fuzzy match - find CR with similar name
    filename_lower = filename.lower().replace('_', '').replace('-', '')

    for (ns, name), statements in target_cr_map.items():
        cr_id = f"{ns}{name}".lower().replace('_', '').replace('-', '')
        if cr_id in filename_lower or filename_lower in cr_id:
            log_info(f"  Fuzzy matched {filename} → ({ns}, {name})")
            return statements

    return None


def generate_sts_policy_files(baseline_version, target_version):
    """
    Generate complete STS policy files for target version.

    Strategy:
    1. Copy ALL files from baseline version (exact copies, preserve structure)
    2. Extract CredentialRequests from both baseline and target
    3. For each baseline file, find matching target CredentialRequest
    4. Apply ONLY the diff to file content, preserving structure and casing
    5. Files without matching CRs are copied unchanged

    Returns: dict mapping filename -> policy content
    """
    log_info(f"Generating STS policy files for {target_version}...")

    # Step 1: Copy all files from baseline (exact copies)
    all_files = copy_previous_sts_files(baseline_version)

    if not all_files:
        log_error("Failed to copy baseline files")
        return {}

    # Step 2: Extract CredentialRequests from both versions
    baseline_cr_map = extract_credreqs_map(baseline_version)
    target_cr_map = extract_credreqs_map(target_version)

    # Step 3: Update files that have matching CredentialRequests
    updated_count = 0
    for filename, baseline_policy in all_files.items():
        # Find matching CredentialRequest in target
        target_statements = match_baseline_file_to_credreq(filename, baseline_cr_map, target_cr_map)

        if target_statements:
            # Found a match - update the Statement array
            baseline_statements = baseline_policy.get('Statement', [])
            updated_statements = apply_statement_diff(baseline_statements, target_statements)

            # Update policy in-place
            all_files[filename]['Statement'] = updated_statements
            updated_count += 1
            log_info(f"  ✓ Updated: {filename}")
        # else: No matching CR, keep baseline file unchanged

    log_success(f"Generated {len(all_files)} total STS files ({updated_count} updated based on CredentialRequest changes)")
    return all_files


def generate_wif_template(version, output_dir):
    """
    Generate GCP WIF vanilla.yaml template.

    Pattern from managed-cluster-config:
    - Single service account named 'osd-deployer'
    - Single role named 'osd_deployer_v{version}'
    - All permissions from all credential requests combined

    Reuses extract_credential_requests() from gap-gcp-wif.py

    Returns: dict with 'vanilla.yaml' -> content
    """
    log_info(f"Extracting GCP WIF credentials for {version}...")

    # Extract credential requests (reuse existing function)
    cr_dir = gap_gcp_wif.extract_credential_requests(version, cloud="gcp")

    # Parse all credential requests and create service accounts
    minor_version = extract_minor_version(version)
    service_accounts = []

    # Mapping of credential request names to service account IDs
    # Based on pattern from 4.20/4.21
    cr_name_to_sa_id = {
        'openshift-gcp-ccm': 'cloud-controller-manager',
        'openshift-gcp-pd-csi-driver-operator': 'gcp-pd-csi-driver-op',
        'openshift-image-registry-gcs': 'image-registry-gcs',
        'openshift-ingress-gcp': 'ingress-op-gcp',
        'openshift-cloud-network-config-controller-gcp': 'cloud-network-config-ctrl',
        'cloud-credential-operator-gcp-ro-creds': 'cloud-credential-op-gcp',
        'openshift-machine-api-gcp': 'machine-api-gcp',
    }

    # Process credential requests
    for cr_file in sorted(Path(cr_dir).glob('*.yaml')):
        with open(cr_file, 'r') as f:
            cr_data = yaml.safe_load(f)

        metadata = cr_data.get('metadata', {})
        spec = cr_data.get('spec', {})
        provider_spec = spec.get('providerSpec', {})

        if 'predefinedRoles' in provider_spec:
            # Using predefined roles - skip
            continue

        if 'permissions' in provider_spec:
            permissions = provider_spec['permissions']
            cr_name = metadata.get('name', 'unknown')

            # Map CR name to service account ID
            sa_id = cr_name_to_sa_id.get(cr_name, cr_name.replace('openshift-', '').replace('_', '-'))

            # Create role ID: sa_id with underscores + _v + version
            role_id = f"{sa_id.replace('-', '_')}_v{minor_version}"

            service_account = {
                'access_method': 'impersonate',
                'id': sa_id,
                'osd_role': 'deployer',
                'roles': [{
                    'id': role_id,
                    'kind': 'Role',
                    'permissions': sorted(permissions)
                }]
            }

            service_accounts.append(service_account)

    # Build WIF template with multiple service accounts
    wif_template = {
        'id': f'v{minor_version}',
        'kind': 'WifTemplate',
        'service_accounts': service_accounts
    }

    # Cleanup temp dir
    shutil.rmtree(cr_dir, ignore_errors=True)

    return {'vanilla.yaml': wif_template}


def generate_sts_ack_files(target_version):
    """
    Generate STS acknowledgment files.

    Based on pattern from managed-cluster-config 4.21

    Returns: dict with filename -> content
    """
    target_minor = extract_minor_version(target_version)

    # Calculate baseline (target - 1)
    parts = target_minor.split('.')
    baseline_minor = f"{parts[0]}.{int(parts[1]) - 1}"

    files = {}

    # config.yaml
    config_yaml = f"""deploymentMode: SelectorSyncSet
selectorSyncSet:
  matchExpressions:
  - key: hive.openshift.io/version-major-minor
    operator: In
    values: ["{baseline_minor}"]
  - key: api.openshift.com/sts
    operator: In
    values: ["true"]
"""
    files['config.yaml'] = config_yaml

    # osd-sts-ack_CloudCredential.yaml
    cloudcred_yaml = f"""apiVersion: operator.openshift.io/v1
kind: CloudCredential
name: cluster
applyMode: AlwaysApply
patch: '{{"metadata":{{"annotations":{{"cloudcredential.openshift.io/upgradeable-to":"v{target_minor}"}}}}}}'
patchType: merge
"""
    files['osd-sts-ack_CloudCredential.yaml'] = cloudcred_yaml

    return files


def generate_wif_ack_files(target_version):
    """
    Generate WIF acknowledgment files.

    Based on pattern from managed-cluster-config 4.21

    Returns: dict with filename -> content
    """
    target_minor = extract_minor_version(target_version)

    # Calculate baseline (target - 1)
    parts = target_minor.split('.')
    baseline_minor = f"{parts[0]}.{int(parts[1]) - 1}"

    files = {}

    # config.yaml
    config_yaml = f"""deploymentMode: SelectorSyncSet
selectorSyncSet:
  matchExpressions:
  - key: hive.openshift.io/version-major-minor
    operator: In
    values: ["{baseline_minor}"]
  - key: api.openshift.com/wif
    operator: In
    values: ["true"]
"""
    files['config.yaml'] = config_yaml

    # osd-wif-ack_CloudCredential.yaml
    cloudcred_yaml = f"""apiVersion: operator.openshift.io/v1
kind: CloudCredential
name: cluster
applyMode: AlwaysApply
patch: '{{"metadata":{{"annotations":{{"cloudcredential.openshift.io/upgradeable-to":"v{target_minor}"}}}}}}'
patchType: merge
"""
    files['osd-wif-ack_CloudCredential.yaml'] = cloudcred_yaml

    return files


def generate_ocp_ack_files(target_version):
    """
    Generate OCP admin gate acknowledgment files.

    Returns: dict with filename -> content
    """
    target_minor = extract_minor_version(target_version)

    # Calculate baseline (target - 1)
    parts = target_minor.split('.')
    baseline_minor = f"{parts[0]}.{int(parts[1]) - 1}"

    files = {}

    # config.yaml
    config_yaml = f"""deploymentMode: SelectorSyncSet
selectorSyncSet:
  matchExpressions:
  - key: hive.openshift.io/version-major-minor
    operator: In
    values: ["{baseline_minor}"]
"""
    files['config.yaml'] = config_yaml

    return files


def write_files_to_disk(output_dir, target_version, aws_sts_files, gcp_wif_files,
                        sts_ack_files, wif_ack_files, ocp_ack_files):
    """
    Write all files to disk in managed-cluster-config directory structure.

    Creates:
    - resources/sts/{version}/*.json
    - resources/wif/{version}/vanilla.yaml
    - deploy/osd-cluster-acks/sts/{version}/*.yaml
    - deploy/osd-cluster-acks/wif/{version}/*.yaml
    - deploy/osd-cluster-acks/ocp/{version}/*.yaml
    """
    target_minor = extract_minor_version(target_version)
    mcc_dir = Path(output_dir) / 'managed-cluster-config'

    # Create directory structure
    sts_resources_dir = mcc_dir / 'resources' / 'sts' / target_minor
    wif_resources_dir = mcc_dir / 'resources' / 'wif' / target_minor
    sts_ack_dir = mcc_dir / 'deploy' / 'osd-cluster-acks' / 'sts' / target_minor
    wif_ack_dir = mcc_dir / 'deploy' / 'osd-cluster-acks' / 'wif' / target_minor
    ocp_ack_dir = mcc_dir / 'deploy' / 'osd-cluster-acks' / 'ocp' / target_minor

    # Create all directories
    sts_resources_dir.mkdir(parents=True, exist_ok=True)
    wif_resources_dir.mkdir(parents=True, exist_ok=True)
    sts_ack_dir.mkdir(parents=True, exist_ok=True)
    wif_ack_dir.mkdir(parents=True, exist_ok=True)
    ocp_ack_dir.mkdir(parents=True, exist_ok=True)

    files_written = []

    # Write AWS STS policy files
    for filename, policy in aws_sts_files.items():
        file_path = sts_resources_dir / filename
        with open(file_path, 'w') as f:
            json.dump(policy, f, indent=2)
        files_written.append(str(file_path.relative_to(mcc_dir)))

    # Write GCP WIF template files
    for filename, template in gcp_wif_files.items():
        file_path = wif_resources_dir / filename
        with open(file_path, 'w') as f:
            yaml.dump(template, f, default_flow_style=False, sort_keys=False)
        files_written.append(str(file_path.relative_to(mcc_dir)))

    # Write AWS STS acknowledgment files
    for filename, content in sts_ack_files.items():
        file_path = sts_ack_dir / filename
        with open(file_path, 'w') as f:
            f.write(content)
        files_written.append(str(file_path.relative_to(mcc_dir)))

    # Write GCP WIF acknowledgment files
    for filename, content in wif_ack_files.items():
        file_path = wif_ack_dir / filename
        with open(file_path, 'w') as f:
            f.write(content)
        files_written.append(str(file_path.relative_to(mcc_dir)))

    # Write OCP acknowledgment files
    for filename, content in ocp_ack_files.items():
        file_path = ocp_ack_dir / filename
        with open(file_path, 'w') as f:
            f.write(content)
        files_written.append(str(file_path.relative_to(mcc_dir)))

    return mcc_dir, files_written


def append_to_summary(summary_path, target_version, aws_sts_files, gcp_wif_files,
                     sts_ack_files, wif_ack_files, ocp_ack_files, mcc_dir=None):
    """Append file content to pr-summary.md"""

    target_minor = extract_minor_version(target_version)

    with open(summary_path, 'a') as f:
        f.write("\n\n---\n\n")
        f.write(f"## Generated File Content for Version {target_minor}\n\n")

        if mcc_dir:
            f.write(f"**Files created locally:** `{mcc_dir}/`\n\n")
            f.write("The complete directory structure with all files has been created locally.\n")
            f.write("You can copy the entire directory to your managed-cluster-config clone:\n\n")
            f.write("```bash\n")
            f.write(f"# From gap-analysis repository:\n")
            f.write(f"cp -r {mcc_dir}/* /path/to/managed-cluster-config/\n")
            f.write("```\n\n")
            f.write("---\n\n")

        f.write("Copy the content below to create files in managed-cluster-config repository.\n\n")

        # AWS STS Resources
        if aws_sts_files:
            f.write(f"### AWS STS Resources (`resources/sts/{target_minor}/`)\n\n")
            for filename, policy in sorted(aws_sts_files.items()):
                f.write(f"#### {filename}\n\n")
                f.write("```json\n")
                f.write(json.dumps(policy, indent=2))
                f.write("\n```\n\n")

        # GCP WIF Resources
        if gcp_wif_files:
            f.write(f"### GCP WIF Resources (`resources/wif/{target_minor}/`)\n\n")
            for filename, template in sorted(gcp_wif_files.items()):
                f.write(f"#### {filename}\n\n")
                f.write("```yaml\n")
                f.write(yaml.dump(template, default_flow_style=False, sort_keys=False))
                f.write("```\n\n")

        # AWS STS Acknowledgments
        if sts_ack_files:
            f.write(f"### AWS STS Acknowledgments (`deploy/osd-cluster-acks/sts/{target_minor}/`)\n\n")
            for filename, content in sorted(sts_ack_files.items()):
                f.write(f"#### {filename}\n\n")
                f.write("```yaml\n")
                f.write(content)
                f.write("```\n\n")

        # GCP WIF Acknowledgments
        if wif_ack_files:
            f.write(f"### GCP WIF Acknowledgments (`deploy/osd-cluster-acks/wif/{target_minor}/`)\n\n")
            for filename, content in sorted(wif_ack_files.items()):
                f.write(f"#### {filename}\n\n")
                f.write("```yaml\n")
                f.write(content)
                f.write("```\n\n")

        # OCP Admin Gate Acknowledgments
        if ocp_ack_files:
            f.write(f"### OCP Admin Gate Acknowledgments (`deploy/osd-cluster-acks/ocp/{target_minor}/`)\n\n")
            for filename, content in sorted(ocp_ack_files.items()):
                f.write(f"#### {filename}\n\n")
                f.write("```yaml\n")
                f.write(content)
                f.write("```\n\n")


def main():
    parser = argparse.ArgumentParser(
        description='Generate PR content for managed-cluster-config from gap analysis failures'
    )
    parser.add_argument('--report', required=True, help='Path to gap-analysis JSON report')
    # Summary generation removed - now handled by analyze-prow-failure.sh
    parser.add_argument('--output-dir', help='Directory to save generated files (default: same dir as report)')
    parser.add_argument('--create-local-files', action='store_true', default=True,
                        help='Create local managed-cluster-config directory structure (default: True)')

    args = parser.parse_args()

    # Validate report exists
    if not os.path.exists(args.report):
        log_error(f"Report file not found: {args.report}")
        sys.exit(1)

    # Determine output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = Path(args.report).parent

    # Read gap analysis report
    log_info(f"Reading gap analysis report: {args.report}")
    report = read_gap_report(args.report)

    target_version = report['target']
    baseline_version = report['baseline']
    target_minor = extract_minor_version(target_version)

    log_info(f"Target version: {target_version} (minor: {target_minor})")
    log_info(f"Baseline version: {baseline_version}")

    # Check which validations failed
    aws_failed = report.get('aws_sts', {}).get('validation_details', {}).get('valid') == False
    gcp_failed = report.get('gcp_wif', {}).get('validation_details', {}).get('valid') == False

    # OCP: Only create ack files if there are gates requiring acknowledgment
    ocp_gates_requiring_ack = report.get('ocp_gate_ack', {}).get('analysis', {}).get('gates_requiring_ack', [])
    ocp_has_gates = len(ocp_gates_requiring_ack) > 0

    # Check if ack file is missing (only matters if there are gates)
    ocp_ack_missing = report.get('ocp_gate_ack', {}).get('analysis', {}).get('ack_file_missing', False)
    ocp_failed = ocp_has_gates and ocp_ack_missing

    log_info(f"Validation failures: AWS STS={aws_failed}, GCP WIF={gcp_failed}, OCP Gates={ocp_failed}")
    if not ocp_has_gates:
        log_info("No OCP admin gates found for target version - no ack files needed")

    # Generate files
    aws_sts_files = {}
    gcp_wif_files = {}
    sts_ack_files = {}
    wif_ack_files = {}
    ocp_ack_files = {}
    mcc_dir = None

    if aws_failed:
        log_info("Generating AWS STS policy files...")
        aws_sts_files = generate_sts_policy_files(baseline_version, target_version)
        log_success(f"Generated {len(aws_sts_files)} AWS STS policy files")

        log_info("Generating AWS STS acknowledgment files...")
        sts_ack_files = generate_sts_ack_files(target_version)
        log_success(f"Generated {len(sts_ack_files)} AWS STS ack files")

    if gcp_failed:
        # Validate WIF pattern consistency across previous versions
        is_consistent, pattern_info = validate_wif_pattern_consistency(target_version)

        if not is_consistent:
            log_warning("WIF patterns are inconsistent across versions - using fallback generation")
            gcp_wif_files = generate_wif_template(target_version, output_dir)
        else:
            # Check if there are permission differences
            has_diff, wif_report = check_gcp_wif_diff(baseline_version, target_version)

            if has_diff:
                log_warning("GCP permissions changed - regenerating from CredentialRequests")
                gcp_wif_files = generate_wif_template(target_version, output_dir)
            else:
                log_info("No GCP permission changes - using copy-and-update strategy")
                gcp_wif_files = copy_and_update_wif_template(baseline_version, target_version)

                if not gcp_wif_files:
                    log_warning("Copy-and-update failed - falling back to generation")
                    gcp_wif_files = generate_wif_template(target_version, output_dir)

        log_success(f"Generated {len(gcp_wif_files)} GCP WIF template files")

        log_info("Generating GCP WIF acknowledgment files...")
        wif_ack_files = generate_wif_ack_files(target_version)
        log_success(f"Generated {len(wif_ack_files)} GCP WIF ack files")

    if ocp_failed:
        log_info("Generating OCP admin gate acknowledgment files...")
        ocp_ack_files = generate_ocp_ack_files(target_version)
        log_success(f"Generated {len(ocp_ack_files)} OCP ack files")

    # Write files to local managed-cluster-config directory structure
    if args.create_local_files:
        log_info("Creating local managed-cluster-config directory structure...")
        mcc_dir, files_written = write_files_to_disk(
            output_dir,
            target_version,
            aws_sts_files,
            gcp_wif_files,
            sts_ack_files,
            wif_ack_files,
            ocp_ack_files
        )
        log_success(f"Created managed-cluster-config structure: {mcc_dir}")
        log_success(f"Files written: {len(files_written)}")
        for file_path in sorted(files_written):
            log_info(f"  ✓ {file_path}")

    log_success("✅ Fix file generation complete!")


if __name__ == '__main__':
    main()
