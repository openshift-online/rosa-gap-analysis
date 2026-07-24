#!/usr/bin/env python3
"""Cluster Installation Validation - Orchestrator for create, validate, report, delete."""

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error, log_warning

# Import cluster creation/deletion functions (files have dashes, use importlib)
classic_module_path = Path(__file__).parent / 'gap-cluster-rosa-classic.py'
spec = importlib.util.spec_from_file_location("gap_cluster_rosa_classic", classic_module_path)
classic_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classic_module)

hcp_module_path = Path(__file__).parent / 'gap-cluster-rosa-hcp.py'
spec = importlib.util.spec_from_file_location("gap_cluster_rosa_hcp", hcp_module_path)
hcp_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hcp_module)

create_classic_cluster = classic_module.create_classic_cluster
delete_classic_cluster = classic_module.delete_classic_cluster
create_hcp_cluster = hcp_module.create_hcp_cluster
delete_hcp_cluster = hcp_module.delete_hcp_cluster


def check_ocm_login():
    """Check OCM login using ocm_auth.sh."""
    log_info("Checking OCM login...")

    ocm_auth_script = Path(__file__).parent / 'lib' / 'ocm_auth.sh'
    logging_sh = Path(__file__).parent / 'lib' / 'logging.sh'

    cmd = ["bash", "-c", f"source {logging_sh} && source {ocm_auth_script} && ocm_authenticate"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if proc.returncode != 0:
        log_error(f"OCM authentication failed: {proc.stderr}")
        return False

    # Verify with ocm whoami
    verify_cmd = ["ocm", "whoami"]
    proc = subprocess.run(verify_cmd, capture_output=True, text=True, check=False)

    if proc.returncode == 0:
        log_success(f"OCM authenticated: {proc.stdout.strip()}")
        return True
    else:
        log_error("OCM verification failed")
        return False


def watch_installation(cluster_id):
    """Watch cluster installation until complete."""
    log_info(f"Watching installation for cluster {cluster_id}")

    cmd = ["rosa", "logs", "install", "-c", cluster_id, "--watch"]
    proc = subprocess.run(cmd, check=False)

    if proc.returncode == 0:
        log_success("Installation watch completed")
        return True
    else:
        log_error("Installation watch failed")
        return False


def wait_for_cluster_ready(cluster_id, max_wait=1200):
    """Wait for cluster to reach ready state."""
    log_info("Waiting for cluster to reach ready state...")

    start = time.time()
    while (time.time() - start) < max_wait:
        cmd = ["rosa", "describe", "cluster", "-c", cluster_id, "--output", "json"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if proc.returncode == 0:
            try:
                data = json.loads(proc.stdout)
                state = data.get('state', '').lower()

                if state == 'ready':
                    log_success("Cluster is ready")
                    return True
                else:
                    log_info(f"Cluster state: {state}, waiting...")
                    time.sleep(30)
            except json.JSONDecodeError:
                log_warning("Failed to parse cluster state, retrying...")
                time.sleep(30)
        else:
            log_warning("Failed to check cluster state, retrying...")
            time.sleep(30)

    log_error(f"Cluster did not reach ready state within {max_wait}s")
    return False


def login_cluster_ocm(cluster_id):
    """Login to cluster using OCM credentials API with retry."""
    log_info(f"Getting kubeconfig from OCM for cluster {cluster_id}")

    # Retry 5 times with 3 minutes gap
    max_retries = 5
    retry_interval = 180  # 3 minutes

    for attempt in range(1, max_retries + 1):
        log_info(f"Attempt {attempt}/{max_retries} to get credentials...")

        cmd = ["ocm", "get", f"/api/clusters_mgmt/v1/clusters/{cluster_id}/credentials"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if proc.returncode == 0:
            try:
                creds = json.loads(proc.stdout)
                kubeconfig = creds.get('kubeconfig')

                if not kubeconfig:
                    log_warning("Kubeconfig not found in OCM response, retrying...")
                    if attempt < max_retries:
                        log_info(f"Waiting {retry_interval}s before retry...")
                        time.sleep(retry_interval)
                        continue
                    else:
                        log_error("Kubeconfig not found after all retries")
                        return False

                # Write kubeconfig to file
                kubeconfig_path = Path(f"/tmp/kubeconfig-{cluster_id}.txt")
                kubeconfig_path.write_text(kubeconfig)

                # Set KUBECONFIG env for this session
                import os
                os.environ['KUBECONFIG'] = str(kubeconfig_path)

                log_success(f"Kubeconfig configured: {kubeconfig_path}")
                return True
            except json.JSONDecodeError as e:
                log_warning(f"Failed to parse OCM credentials: {e}")
                if attempt < max_retries:
                    log_info(f"Waiting {retry_interval}s before retry...")
                    time.sleep(retry_interval)
                    continue
                else:
                    log_error("Failed to parse credentials after all retries")
                    return False
        else:
            log_warning(f"Failed to get credentials (attempt {attempt}/{max_retries}): {proc.stderr}")
            if attempt < max_retries:
                log_info(f"Waiting {retry_interval}s before retry...")
                time.sleep(retry_interval)
            else:
                log_error("Failed to get credentials after all retries")
                return False

    return False


def run_validations(cluster_id):
    """Run ClusterOperator and Node validations."""
    log_info("Running validations...")

    # TODO: Implement validation logic
    # 1. oc get co -o json → Check Available=True, Degraded=False
    # 2. oc get nodes -o json → Check Ready=True
    # Return validation results dict

    log_info("Validations - TO BE IMPLEMENTED")
    return {}


def generate_reports(validation_results, version, region, channel_group, report_dir):
    """Generate HTML and JSON reports."""
    log_info("Generating reports...")

    # TODO: Implement report generation
    # Use Jinja2 templates for HTML
    # Generate JSON report

    log_info("Report generation - TO BE IMPLEMENTED")


def main():
    parser = argparse.ArgumentParser(description='Cluster Installation Validation')
    parser.add_argument('--version', required=True, help='OCP version')
    parser.add_argument('--topology', choices=['classic', 'hcp'], required=True, help='Cluster topology')
    parser.add_argument('--region', required=True, help='AWS region')
    parser.add_argument('--channel-group', required=True, help='Channel group')
    parser.add_argument('--billing-account', help='Billing account (required for HCP)')
    parser.add_argument('--report-dir', default='reports', help='Report directory')

    args = parser.parse_args()

    # Validate HCP requirements
    if args.topology == 'hcp' and not args.billing_account:
        log_error("--billing-account is required for HCP")
        sys.exit(1)

    log_info("Cluster Installation Validation Orchestrator")
    log_info(f"Topology: {args.topology}")
    log_info(f"Version: {args.version}")

    # Step 1: Check OCM login
    if not check_ocm_login():
        log_error("OCM login check failed")
        sys.exit(1)

    # Step 2: Create cluster (calls appropriate module based on topology)
    cluster_id = None
    work_dir = None
    cluster_name = None

    if args.topology == 'classic':
        cluster_id = create_classic_cluster(args.version, args.region, args.channel_group)
        if not cluster_id:
            log_error("Classic cluster creation failed")
            sys.exit(1)
    else:
        # HCP
        cluster_id, work_dir, cluster_name = create_hcp_cluster(
            args.version, args.region, args.channel_group, args.billing_account
        )
        if not cluster_id:
            log_error("HCP cluster creation failed")
            sys.exit(1)

    try:
        # Step 3: Watch installation
        if not watch_installation(cluster_id):
            log_error("Installation watch failed")
            sys.exit(1)

        # Step 4: Wait for cluster ready
        if not wait_for_cluster_ready(cluster_id):
            log_error("Cluster did not reach ready state")
            sys.exit(1)

        # Step 5: Login using OCM
        if not login_cluster_ocm(cluster_id):
            log_error("Cluster login failed")
            sys.exit(1)

        # Step 6: Run validations
        validation_results = run_validations(cluster_id)

        # Step 7: Generate reports
        generate_reports(validation_results, args.version, args.region, args.channel_group, args.report_dir)

    finally:
        # Step 8: Always delete cluster and resources
        log_info("Cleanup: Deleting cluster and resources...")
        if args.topology == 'classic':
            delete_classic_cluster(cluster_id)
        else:
            # HCP
            if cluster_id and work_dir and cluster_name:
                delete_hcp_cluster(cluster_id, work_dir, args.region, cluster_name)

    log_success("Cluster Installation Validation completed")
    sys.exit(0)


if __name__ == '__main__':
    main()
