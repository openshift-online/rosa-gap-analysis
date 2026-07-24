#!/usr/bin/env python3
"""ROSA HCP Cluster Creation and Deletion - Pure function library."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error, log_warning


def create_hcp_cluster(version, region, channel_group, billing_account):
    """
    Create ROSA HCP cluster following Red Hat official documentation order.

    Order: VPC → account-roles → oidc-config → operator-roles → cluster

    Args:
        version: OCP version (e.g., "4.20.28")
        region: AWS region (e.g., "us-east-1")
        channel_group: Channel group (e.g., "stable", "candidate")
        billing_account: Billing account ID

    Returns:
        (cluster_id: str, work_dir: Path, cluster_name: str) or (None, None, None) on failure
    """
    import time

    version_short = ''.join(c for c in version.split('.')[0:2] if c.isdigit())
    timestamp = datetime.now(timezone.utc).strftime('%m%d%H%M')
    # HCP cluster name must be < 16 chars: "hcp42-07241949" = 14 chars
    cluster_name = f"hcp{version_short}-{timestamp}"
    operator_prefix = f"gap-hcp-{timestamp}"

    # Step 1: Setup Terraform VPC
    work_dir = Path("hypershift-tf")
    work_dir.mkdir(exist_ok=True)

    tf_file = work_dir / "setup-vpc.tf"
    if not tf_file.exists():
        log_info("Step 1: Downloading Terraform VPC template...")
        curl_cmd = [
            "curl", "-s", "-o", str(tf_file),
            "https://raw.githubusercontent.com/openshift-cs/OpenShift-Troubleshooting-Templates/master/rosa-hcp-terraform/setup-vpc.tf"
        ]
        proc = subprocess.run(curl_cmd, check=False)
        if proc.returncode != 0:
            log_error("Failed to download setup-vpc.tf")
            return None, None, None
        log_success("Terraform template downloaded")

    log_info("Step 1: Initializing Terraform...")
    proc = subprocess.run(["terraform", "init"], cwd=str(work_dir), check=False)
    if proc.returncode != 0:
        log_error("Terraform init failed")
        return None, None, None

    log_info("Step 1: Creating Terraform plan...")
    plan_cmd = [
        "terraform", "plan", "-out", "rosa.plan",
        "-var", f"aws_region={region}",
        "-var", f"cluster_name={cluster_name}"
    ]
    proc = subprocess.run(plan_cmd, cwd=str(work_dir), check=False)
    if proc.returncode != 0:
        log_error("Terraform plan failed")
        return None, None, None

    log_info("Step 1: Applying Terraform plan...")
    proc = subprocess.run(["terraform", "apply", "rosa.plan"], cwd=str(work_dir), check=False)
    if proc.returncode != 0:
        log_error("Terraform apply failed")
        return None, None, None
    log_success("VPC infrastructure created")

    # Get subnet IDs
    log_info("Step 1: Retrieving subnet IDs...")
    private_subnet_proc = subprocess.run(
        ["terraform", "output", "-raw", "cluster-private-subnet"],
        cwd=str(work_dir), capture_output=True, text=True, check=False
    )
    public_subnet_proc = subprocess.run(
        ["terraform", "output", "-raw", "cluster-public-subnet"],
        cwd=str(work_dir), capture_output=True, text=True, check=False
    )

    if private_subnet_proc.returncode != 0 or public_subnet_proc.returncode != 0:
        log_error("Failed to get subnet IDs from Terraform")
        return None, None, None

    private_subnet = private_subnet_proc.stdout.strip()
    public_subnet = public_subnet_proc.stdout.strip()
    log_success(f"Subnets: public={public_subnet}, private={private_subnet}")

    # Step 2: Tag subnets
    log_info("Step 2: Tagging subnets for ROSA HCP...")
    public_tag_cmd = [
        "aws", "ec2", "create-tags",
        "--resources", public_subnet,
        "--tags", "Key=kubernetes.io/role/elb,Value=1",
        "--region", region
    ]
    proc = subprocess.run(public_tag_cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        log_error(f"Failed to tag public subnet: {proc.stderr}")
        return None, None, None

    private_tag_cmd = [
        "aws", "ec2", "create-tags",
        "--resources", private_subnet,
        "--tags", "Key=kubernetes.io/role/internal-elb,Value=1",
        "--region", region
    ]
    proc = subprocess.run(private_tag_cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        log_error(f"Failed to tag private subnet: {proc.stderr}")
        return None, None, None
    log_success("Subnets tagged successfully")

    # Step 3: Create account-wide IAM roles
    log_info("Step 3: Creating account-wide IAM roles...")
    create_roles_cmd = [
        "rosa", "create", "account-roles",
        "--hosted-cp",
        "--force-policy-creation",
        "--region", region,
        "--mode", "auto",
        "--yes"
    ]
    proc = subprocess.run(create_roles_cmd, check=False)
    if proc.returncode != 0:
        log_error("Failed to create account roles")
        return None, None, None
    log_success("Account-wide IAM roles created")

    # Step 4: Create OIDC config
    log_info("Step 4: Creating OIDC configuration...")
    create_oidc_cmd = [
        "rosa", "create", "oidc-config",
        "--mode", "auto",
        "--managed",
        "--region", region,
        "--yes"
    ]
    proc = subprocess.run(create_oidc_cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        log_error(f"Failed to create OIDC config: {proc.stderr}")
        return None, None, None

    # Get OIDC config ID from list
    time.sleep(5)  # Wait for OIDC config to be available
    oidc_list_cmd = ["rosa", "list", "oidc-config", "--region", region, "-ojson"]
    proc = subprocess.run(oidc_list_cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        log_error("Failed to list OIDC configs")
        return None, None, None

    try:
        oidc_configs = json.loads(proc.stdout)
        oidc_id = None
        for config in oidc_configs:
            if config.get('managed') and not config.get('last_used_timestamp'):
                oidc_id = config.get('id')
                break

        if not oidc_id:
            log_error("No available OIDC config found")
            return None, None, None

        log_success(f"OIDC config created: {oidc_id}")
    except json.JSONDecodeError:
        log_error("Failed to parse OIDC config JSON")
        return None, None, None

    # Step 5: Create operator roles
    log_info("Step 5: Creating operator roles...")
    # Get AWS account ID
    account_id_proc = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        capture_output=True, text=True, check=False
    )
    if account_id_proc.returncode != 0:
        log_error("Failed to get AWS account ID")
        return None, None, None

    account_id = account_id_proc.stdout.strip()
    installer_role_arn = f"arn:aws:iam::{account_id}:role/ManagedOpenShift-HCP-ROSA-Installer-Role"

    create_op_roles_cmd = [
        "rosa", "create", "operator-roles",
        "--prefix", operator_prefix,
        "--oidc-config-id", oidc_id,
        "--installer-role-arn", installer_role_arn,
        "--hosted-cp",
        "--region", region,
        "--mode", "auto",
        "--yes"
    ]
    proc = subprocess.run(create_op_roles_cmd, check=False)
    if proc.returncode != 0:
        log_error("Failed to create operator roles")
        return None, None, None
    log_success("Operator roles created")

    # Step 6: Create HCP cluster
    log_info("Step 6: Creating ROSA HCP cluster")
    log_info(f"  Cluster name: {cluster_name}")
    log_info(f"  Version: {version}")
    log_info(f"  Region: {region}")
    log_info(f"  Channel: {channel_group}")

    create_cmd = [
        "rosa", "create", "cluster",
        "--cluster-name", cluster_name,
        "--version", version,
        "--channel-group", channel_group,
        "--region", region,
        "--hosted-cp",
        "--subnet-ids", f"{public_subnet},{private_subnet}",
        "--machine-cidr", "10.0.0.0/16",
        "--operator-roles-prefix", operator_prefix,
        "--oidc-config-id", oidc_id,
        "--billing-account", billing_account,
        "--sts",
        "--mode", "auto",
        "--yes"
    ]

    proc = subprocess.run(create_cmd, check=False)
    if proc.returncode != 0:
        log_error("Failed to create HCP cluster")
        return None, None, None

    # Step 7: Get cluster ID
    log_info("Step 7: Retrieving cluster ID...")
    describe_cmd = ["rosa", "describe", "cluster", "-c", cluster_name, "--region", region, "--output", "json"]
    proc = subprocess.run(describe_cmd, capture_output=True, text=True, check=False)

    if proc.returncode != 0:
        log_error(f"Failed to get cluster ID: {proc.stderr}")
        return None, None, None

    try:
        cluster_data = json.loads(proc.stdout)
        cluster_id = cluster_data.get('id')
        if not cluster_id:
            log_error("Cluster ID not found in response")
            return None, None, None

        log_success(f"HCP cluster created successfully: {cluster_id}")
        return cluster_id, work_dir, cluster_name
    except json.JSONDecodeError as e:
        log_error(f"Failed to parse cluster data: {e}")
        return None, None, None


def delete_hcp_cluster(cluster_id, work_dir, region, cluster_name):
    """
    Delete ROSA HCP cluster and cleanup all resources.

    Args:
        cluster_id: Cluster ID to delete
        work_dir: Terraform work directory (Path object)
        region: AWS region
        cluster_name: Cluster name

    Returns:
        True on success, False on failure
    """
    import time

    log_info(f"Deleting HCP cluster {cluster_id}...")

    # Step 1: Delete cluster and wait
    delete_cmd = ["rosa", "delete", "cluster", "-c", cluster_id, "--region", region, "--yes", "--watch"]
    proc = subprocess.run(delete_cmd, check=False)

    if proc.returncode != 0:
        log_warning("Cluster deletion command failed or was interrupted")

    # Wait for cluster to fully delete
    log_info("Waiting for cluster deletion to complete...")
    time.sleep(30)
    log_success(f"Cluster {cluster_id} deleted")

    # Step 2: Delete OIDC provider
    log_info("Deleting OIDC provider...")
    delete_oidc_cmd = ["rosa", "delete", "oidc-provider", "-c", cluster_id, "--region", region, "--mode", "auto", "--yes"]
    proc = subprocess.run(delete_oidc_cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        log_success("OIDC provider deleted")
    else:
        log_warning(f"Failed to delete OIDC provider: {proc.stderr}")

    # Step 3: Delete operator roles
    log_info("Deleting operator roles...")
    delete_op_roles_cmd = ["rosa", "delete", "operator-roles", "-c", cluster_id, "--region", region, "--mode", "auto", "--yes"]
    proc = subprocess.run(delete_op_roles_cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        log_success("Operator roles deleted")
    else:
        log_warning(f"Failed to delete operator roles: {proc.stderr}")

    # Step 4: Terraform destroy VPC
    log_info("Destroying Terraform VPC infrastructure...")
    destroy_cmd = [
        "terraform", "destroy",
        "-var", f"aws_region={region}",
        "-var", f"cluster_name={cluster_name}",
        "-auto-approve"
    ]
    proc = subprocess.run(destroy_cmd, cwd=str(work_dir), check=False)

    if proc.returncode == 0:
        log_success("VPC infrastructure destroyed")
    else:
        log_warning("Failed to destroy VPC infrastructure")

    # Step 5: Delete account roles
    log_info("Deleting account-wide IAM roles...")
    delete_account_roles_cmd = ["rosa", "delete", "account-roles", "--prefix", "ManagedOpenShift", "--region", region, "--mode", "auto", "--yes"]
    proc = subprocess.run(delete_account_roles_cmd, capture_output=True, text=True, check=False)

    if proc.returncode == 0:
        log_success("Account-wide IAM roles deleted")
    else:
        log_warning(f"Failed to delete account roles: {proc.stderr}")

    return True
