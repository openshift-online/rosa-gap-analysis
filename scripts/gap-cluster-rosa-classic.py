#!/usr/bin/env python3
"""ROSA Classic Cluster Creation and Deletion - Pure function library."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error, log_warning


def create_classic_cluster(version, region, channel_group):
    """
    Create ROSA Classic cluster with auto account role creation.
    Always creates account roles before cluster creation.

    Args:
        version: OCP version (e.g., "4.20.28")
        region: AWS region (e.g., "us-east-1")
        channel_group: Channel group (e.g., "stable", "candidate")

    Returns:
        cluster_id (str) or None on failure
    """
    # Step 1: Always auto-create account roles
    log_info("Step 1: Auto-creating Classic account roles...")
    create_cmd = [
        "rosa", "create", "account-roles",
        "--classic",
        "--mode", "auto",
        "--region", region,
        "--yes"
    ]
    proc = subprocess.run(create_cmd, stdin=subprocess.DEVNULL, check=False)
    if proc.returncode != 0:
        log_error("Failed to create Classic account roles")
        return None
    log_success("Classic account roles created successfully")

    # Step 2: Create cluster
    version_short = ''.join(c for c in version.split('.')[0:2] if c.isdigit())
    timestamp = datetime.now(timezone.utc).strftime('%m%d%H%M')
    cluster_name = f"gap-{version_short}-classic-{timestamp}"

    log_info("Step 2: Creating ROSA Classic cluster")
    log_info(f"  Cluster name: {cluster_name}")
    log_info(f"  Version: {version}")
    log_info(f"  Region: {region}")
    log_info(f"  Channel: {channel_group}")

    create_cmd = [
        "rosa", "create", "cluster",
        "--cluster-name", cluster_name,
        "--version", version,
        "--region", region,
        "--channel-group", channel_group,
        "--sts",
        "--mode", "auto",
        "--yes"
    ]

    proc = subprocess.run(create_cmd, check=False)
    if proc.returncode != 0:
        log_error("Failed to create cluster")
        return None

    # Step 3: Get cluster ID
    log_info("Step 3: Retrieving cluster ID...")
    describe_cmd = ["rosa", "describe", "cluster", "-c", cluster_name, "--output", "json"]
    proc = subprocess.run(describe_cmd, capture_output=True, text=True, check=False)

    if proc.returncode != 0:
        log_error(f"Failed to get cluster ID: {proc.stderr}")
        return None

    try:
        cluster_data = json.loads(proc.stdout)
        cluster_id = cluster_data.get('id')
        if not cluster_id:
            log_error("Cluster ID not found in response")
            return None

        log_success(f"Cluster created successfully: {cluster_id}")
        return cluster_id
    except json.JSONDecodeError as e:
        log_error(f"Failed to parse cluster data: {e}")
        return None


def delete_classic_cluster(cluster_id):
    """
    Delete ROSA Classic cluster and cleanup account roles.
    Always deletes account roles after cluster deletion.

    Args:
        cluster_id: Cluster ID to delete

    Returns:
        True on success, False on failure
    """
    import time

    log_info(f"Deleting cluster {cluster_id}...")

    delete_cmd = ["rosa", "delete", "cluster", "-c", cluster_id, "--yes", "--watch"]
    proc = subprocess.run(delete_cmd, check=False)

    if proc.returncode != 0:
        log_warning("Cluster deletion command failed or was interrupted")
        # Continue to try deleting account roles anyway

    # Wait a bit more to ensure cluster is fully deleted
    log_info("Waiting for cluster deletion to complete...")
    time.sleep(30)

    log_success(f"Cluster {cluster_id} deleted")

    # Always delete account roles
    log_info("Deleting Classic account roles...")
    delete_roles_cmd = ["rosa", "delete", "account-roles", "--prefix", "ManagedOpenShift", "--mode", "auto", "--yes"]
    proc = subprocess.run(delete_roles_cmd, capture_output=True, text=True, check=False)

    if proc.returncode == 0:
        log_success("Classic account roles deleted successfully")
    else:
        log_warning(f"Failed to delete account roles: {proc.stderr}")

    return True
