#!/usr/bin/env python3
"""Marketplace Enablement Checks - AWS and GCP marketplace verification for ROSA/OCP versions."""

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error, log_warning


CINCINNATI_URL = "https://api.openshift.com/api/upgrades_info/graph"


def _get_cincinnati_versions(channel, arch="amd64"):
    """Query Cincinnati graph API for versions in a channel. Returns a set of version strings."""
    url = f"{CINCINNATI_URL}?channel={channel}&arch={arch}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return {node["version"] for node in data.get("nodes", [])}
    except Exception as e:
        log_warning(f"Failed to query Cincinnati for channel '{channel}': {e}")
        return set()


def _get_rosa_versions(channel, major_minor, hosted_cp=False):
    """Query rosa CLI for versions in a channel. Returns a set of version strings."""
    cmd = ["rosa", "list", "versions", "--channel-group", channel]
    if hosted_cp:
        cmd.append("--hosted-cp")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    versions = set()
    for line in proc.stdout.splitlines():
        parts = line.strip().split()
        if parts and parts[0].startswith(major_minor):
            versions.add(parts[0])
    return versions


def check_aws_marketplace_enablement(target_version):
    """Verify AWS marketplace enablement for ROSA Classic and ROSA HCP.

    Compares Cincinnati (source of truth for OCP channel content) against
    what ROSA/OCM exposes via clusterimagesets. A version in Cincinnati but
    not in ROSA means clusterimagesets haven't been enabled for that channel.
    """
    major_minor = ".".join(target_version.split(".")[:2])
    ga_channels = ["stable", "fast", "candidate"]
    try:
        minor_val = int(major_minor.split(".")[1])
        if minor_val % 2 == 0:
            ga_channels.append("eus")
    except Exception:
        pass
    channels = ga_channels + ["nightly"]

    rosa_path = shutil.which("rosa")
    if not rosa_path:
        log_warning("ROSA CLI binary missing in PATH. Skipped AWS Marketplace enablement check.")
        return {
            'status': 'WARN',
            'message': 'ROSA CLI binary missing in PATH. Skipped AWS Marketplace enablement check.',
            'channels': {}
        }

    log_info(f"Checking AWS Marketplace enablement across channels {channels}...")
    cli_results = {}

    for chan in channels:
        cincinnati_versions = _get_cincinnati_versions(f"{chan}-{major_minor}")
        rosa_classic = _get_rosa_versions(chan, major_minor, hosted_cp=False)
        rosa_hcp = _get_rosa_versions(chan, major_minor, hosted_cp=True)

        if rosa_classic is None:
            log_warning(f"Failed to query 'rosa list versions' for channel group '{chan}'.")
            return {
                'status': 'WARN',
                'message': f"Failed to query 'rosa list versions' for '{chan}'. Ensure 'rosa' CLI is logged in.",
                'channels': {}
            }

        in_cincinnati = len(cincinnati_versions) > 0
        in_rosa_classic = len(rosa_classic) > 0
        in_rosa_hcp = len(rosa_hcp) > 0 if rosa_hcp is not None else False

        cli_results[chan] = {
            "cincinnati": in_cincinnati,
            "cincinnati_count": len(cincinnati_versions),
            "rosa_classic": in_rosa_classic,
            "rosa_hcp": in_rosa_hcp,
            "rosa_classic_output": sorted(rosa_classic)[-1] if rosa_classic else "",
            "rosa_hcp_output": sorted(rosa_hcp)[-1] if rosa_hcp else "",
        }

        if in_cincinnati and in_rosa_classic:
            log_info(f"  {chan}: Cincinnati has {len(cincinnati_versions)} version(s), ROSA enabled")
        elif in_cincinnati and not in_rosa_classic:
            log_warning(f"  {chan}: Cincinnati has {len(cincinnati_versions)} version(s), but ROSA clusterimagesets NOT enabled")
        elif not in_cincinnati and not in_rosa_classic:
            log_info(f"  {chan}: not published yet")

    enabled_channels = [
        chan for chan in channels
        if cli_results[chan]["rosa_classic"] or cli_results[chan]["rosa_hcp"]
    ]
    gaps = [
        chan for chan in ga_channels
        if cli_results[chan]["cincinnati"] and not cli_results[chan]["rosa_classic"]
    ]

    if gaps:
        log_error(f"Clusterimagesets not enabled for: {', '.join(gaps)} (Cincinnati has versions but ROSA does not).")
        return {
            'status': 'FAIL',
            'message': f"Clusterimagesets not enabled for: {', '.join(gaps)}.",
            'channels': cli_results,
            'gaps': gaps
        }
    elif enabled_channels:
        log_success(f"AWS Marketplace enablement verified in: {', '.join(enabled_channels)}.")
        return {
            'status': 'PASS',
            'message': f"AWS Marketplace enablement verified in: {', '.join(enabled_channels)}.",
            'channels': cli_results,
            'gaps': []
        }
    else:
        log_info("No versions published to any channel yet.")
        return {
            'status': 'PASS',
            'message': "No versions published to any channel yet (pre-GA).",
            'channels': cli_results,
            'gaps': []
        }


def check_gcp_marketplace_enablement(target_version):
    """Verify GCP marketplace enablement."""
    major_minor = ".".join(target_version.split(".")[:2])
    ga_channels = ["stable", "fast", "candidate"]
    try:
        minor_val = int(major_minor.split(".")[1])
        if minor_val % 2 == 0:
            ga_channels.append("eus")
    except Exception:
        pass
    channels = ga_channels + ["nightly"]

    ocm_path = shutil.which("ocm")
    if not ocm_path:
        log_warning("OCM CLI binary missing in PATH. Skipped GCP Marketplace enablement check.")
        return {
            'status': 'WARN',
            'message': 'OCM CLI binary missing in PATH. Skipped GCP Marketplace enablement check.',
            'channels': {}
        }

    log_info(f"Checking GCP Marketplace enablement across channels {channels}...")
    cli_results = {}

    for chan in channels:
        cincinnati_versions = _get_cincinnati_versions(f"{chan}-{major_minor}")

        cmd_gcp = ["ocm", "list", "versions", "--channel-group", chan, "--marketplace-gcp=true"]
        proc_gcp = subprocess.run(cmd_gcp, capture_output=True, text=True, check=False)
        if proc_gcp.returncode != 0:
            log_warning(f"Failed to query 'ocm' CLI versions for channel group '{chan}'.")
            return {
                'status': 'WARN',
                'message': f"Failed to query 'ocm' CLI for '{chan}'. Ensure 'ocm' CLI is logged in.",
                'channels': {}
            }

        gcp_versions = set()
        for line in proc_gcp.stdout.splitlines():
            parts = line.strip().split()
            if parts and parts[0].startswith(major_minor):
                clean_version = parts[0]
                if clean_version.endswith(f"-{chan}"):
                    clean_version = clean_version[: -len(f"-{chan}")]
                gcp_versions.add(clean_version)

        in_cincinnati = len(cincinnati_versions) > 0
        in_gcp = len(gcp_versions) > 0

        cli_results[chan] = {
            "cincinnati": in_cincinnati,
            "cincinnati_count": len(cincinnati_versions),
            "gcp_marketplace": in_gcp,
            "gcp_marketplace_output": sorted(gcp_versions)[-1] if gcp_versions else "",
        }

        if in_cincinnati and in_gcp:
            log_info(f"  {chan}: Cincinnati has {len(cincinnati_versions)} version(s), GCP enabled")
        elif in_cincinnati and not in_gcp:
            log_warning(f"  {chan}: Cincinnati has {len(cincinnati_versions)} version(s), but GCP clusterimagesets NOT enabled")
        elif not in_cincinnati and not in_gcp:
            log_info(f"  {chan}: not published yet")

    enabled_channels = [
        chan for chan in channels
        if cli_results[chan]["gcp_marketplace"]
    ]
    gaps = [
        chan for chan in ga_channels
        if cli_results[chan]["cincinnati"] and not cli_results[chan]["gcp_marketplace"]
    ]

    if gaps:
        log_error(f"Clusterimagesets not enabled for: {', '.join(gaps)} (Cincinnati has versions but GCP does not).")
        return {
            'status': 'FAIL',
            'message': f"Clusterimagesets not enabled for: {', '.join(gaps)}.",
            'channels': cli_results,
            'gaps': gaps
        }
    elif enabled_channels:
        log_success(f"GCP Marketplace enablement verified in: {', '.join(enabled_channels)}.")
        return {
            'status': 'PASS',
            'message': f"GCP Marketplace enablement verified in: {', '.join(enabled_channels)}.",
            'channels': cli_results,
            'gaps': []
        }
    else:
        log_info("No versions published to any channel yet.")
        return {
            'status': 'PASS',
            'message': "No versions published to any channel yet (pre-GA).",
            'channels': cli_results,
            'gaps': []
        }
