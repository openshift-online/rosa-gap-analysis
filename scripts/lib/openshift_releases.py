#!/usr/bin/env python3
"""OpenShift release version utilities using release streams API."""

import json
import sys
from urllib.request import urlopen, Request
from urllib.error import URLError

from common import log_info, log_error


SIPPY_API = "https://sippy.dptools.openshift.org/api/releases"
ACCEPTED_STREAMS_API = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted"
STABLE_STREAM = "4-stable"
DEV_PREVIEW_STREAM = "4-dev-preview"


def fetch_sippy_ga_dates():
    """Fetch GA dates from Sippy API."""
    try:
        req = Request(SIPPY_API, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=10) as response:
            data = response.read()
            return json.loads(data).get('ga_dates', {})
    except (URLError, json.JSONDecodeError) as e:
        log_error(f"Failed to fetch GA dates from Sippy API: {e}")
        sys.exit(1)


def get_latest_ga_version():
    """Get the latest GA version from Sippy API."""
    ga_dates = fetch_sippy_ga_dates()
    if not ga_dates:
        log_error("No GA versions found in Sippy API")
        sys.exit(1)

    # Sort versions and get the latest
    versions = sorted(ga_dates.keys(), key=lambda v: list(map(int, v.split('.'))))
    return versions[-1]


def fetch_accepted_streams():
    """
    Fetch all accepted release streams in a single API call.

    Returns:
        dict: {"4-stable": ["4.22.0-rc.0", "4.21.11", ...], "4-dev-preview": [...]}
    """
    try:
        req = Request(ACCEPTED_STREAMS_API, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except (URLError, json.JSONDecodeError) as e:
        log_error(f"Failed to fetch accepted release streams: {e}")
        sys.exit(1)


def get_latest_stable_version(ga_version=None):
    """
    Get the latest stable OpenShift version from accepted streams, filtered by GA version line.

    Args:
        ga_version: GA version line to filter by (e.g., "4.21"). If None, auto-detects from Sippy.

    Returns:
        Latest stable version matching the GA line (e.g., "4.21.11")
    """
    if ga_version is None:
        ga_version = get_latest_ga_version()

    # Fetch accepted streams (single API call)
    streams = fetch_accepted_streams()
    stable_versions = streams.get(STABLE_STREAM, [])

    if not stable_versions:
        log_error(f"No versions found in {STABLE_STREAM} accepted stream")
        sys.exit(1)

    # Filter to match GA version line (e.g., 4.21.x)
    # Versions are already sorted newest first in the accepted API
    matching_versions = [v for v in stable_versions if v.startswith(f"{ga_version}.")]

    if not matching_versions:
        log_error(f"No stable versions found matching GA version line {ga_version}.x")
        sys.exit(1)

    return matching_versions[0]


def get_latest_candidate_version(dev_version=None):
    """
    Get the latest candidate OpenShift version using dual-source priority from accepted streams.

    Priority 1: Check 4-stable for RC version (e.g., 4.22.0-rc.*)
    Priority 2: Fall back to 4-dev-preview for EC version (e.g., 4.22.0-ec.*)

    Args:
        dev_version: Dev version line to search for (e.g., "4.22"). If None, auto-calculates from GA+1.

    Returns:
        Latest candidate version (RC from 4-stable or EC from 4-dev-preview)
    """
    if dev_version is None:
        ga_version = get_latest_ga_version()
        parts = ga_version.split('.')
        dev_minor = int(parts[1]) + 1
        dev_version = f"{parts[0]}.{dev_minor}"

    # Fetch accepted streams (single API call)
    streams = fetch_accepted_streams()

    # Priority 1: Check 4-stable for RC version (e.g., 4.22.0-rc.*)
    stable_versions = streams.get(STABLE_STREAM, [])
    rc_versions = [v for v in stable_versions if v.startswith(f"{dev_version}.0-rc.")]

    if rc_versions:
        # Found RC in 4-stable, return it (already sorted newest first)
        return rc_versions[0]

    # Priority 2: Check 4-dev-preview for EC version (e.g., 4.22.0-ec.*)
    dev_versions = streams.get(DEV_PREVIEW_STREAM, [])
    ec_versions = [v for v in dev_versions if v.startswith(f"{dev_version}.0-ec.")]

    if ec_versions:
        # Found EC in 4-dev-preview, return it (already sorted newest first)
        return ec_versions[0]

    # No RC or EC found
    log_error(f"No candidate version found for {dev_version} (checked RC in 4-stable and EC in 4-dev-preview)")
    sys.exit(1)


def get_latest_dev_nightly_version():
    """Get the latest dev nightly OpenShift version."""
    # Get the latest GA version
    ga_version = get_latest_ga_version()

    # Calculate dev version (GA + 1)
    parts = ga_version.split('.')
    dev_minor = int(parts[1]) + 1
    dev_version = f"{parts[0]}.{dev_minor}"

    try:
        url = f"{RELEASE_STREAM_BASE}/{dev_version}.0-0.nightly/latest?rel=1"
        req = Request(url, headers={'User-Agent': 'gap-analysis-script'})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            nightly_name = data.get('name')
            if not nightly_name:
                log_error(f"No nightly version found for {dev_version}")
                sys.exit(1)
            return nightly_name
    except (URLError, json.JSONDecodeError, KeyError) as e:
        log_error(f"Failed to fetch latest nightly version: {e}")
        sys.exit(1)


def extract_minor_version(version_string):
    """Extract minor version (e.g., '4.21' from '4.21.5')."""
    parts = version_string.split('.')
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return version_string


def resolve_baseline_version(cli_arg=None, env_var=None):
    """
    Resolve baseline version with precedence: CLI > ENV > Auto-detect.

    If CLI/ENV value is a minor version (e.g., "4.21"), it will be resolved to the
    latest patch version from 4-stable stream (e.g., "4.21.7").

    Args:
        cli_arg: Version from CLI argument (--baseline)
        env_var: Version from environment variable (BASE_VERSION)

    Returns:
        str: Resolved version string
    """
    if cli_arg:
        # Check if this is a minor version (X.Y format) that needs resolution
        if cli_arg.count('.') == 1:
            log_info(f"Resolving baseline minor version from CLI: {cli_arg}")
            version = get_latest_stable_version(ga_version=cli_arg)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using baseline version from CLI: {cli_arg}")
            return cli_arg
    elif env_var:
        # Check if this is a minor version (X.Y format) that needs resolution
        if env_var.count('.') == 1:
            log_info(f"Resolving baseline minor version from BASE_VERSION env: {env_var}")
            version = get_latest_stable_version(ga_version=env_var)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using baseline version from BASE_VERSION env: {env_var}")
            return env_var
    else:
        log_info("Auto-detecting baseline version from latest stable...")
        version = get_latest_stable_version()
        log_info(f"Auto-detected baseline version: {version}")
        return version


def resolve_target_version(cli_arg=None, env_var=None):
    """
    Resolve target version with precedence: CLI > ENV > Auto-detect.

    If CLI/ENV value is a minor version (e.g., "4.22"), it will be resolved to the
    latest candidate (RC from 4-stable or EC from 4-dev-preview).

    Special keywords: NIGHTLY, CANDIDATE

    Args:
        cli_arg: Version from CLI argument (--target)
        env_var: Version from environment variable (TARGET_VERSION)

    Returns:
        str: Resolved version string
    """
    if cli_arg:
        # Check if this is a minor version (X.Y format) that needs resolution
        if cli_arg.count('.') == 1:
            log_info(f"Resolving target minor version from CLI: {cli_arg}")
            version = get_latest_candidate_version(dev_version=cli_arg)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using target version from CLI: {cli_arg}")
            return cli_arg
    elif env_var:
        # Check if TARGET_VERSION is a special keyword
        if env_var.upper() == 'NIGHTLY':
            log_info("TARGET_VERSION=NIGHTLY detected, using latest dev nightly...")
            version = get_latest_dev_nightly_version()
            log_info(f"Auto-detected nightly target version: {version}")
            return version
        elif env_var.upper() == 'CANDIDATE':
            log_info("TARGET_VERSION=CANDIDATE detected, using latest candidate...")
            version = get_latest_candidate_version()
            log_info(f"Auto-detected candidate target version: {version}")
            return version
        # Check if this is a minor version (X.Y format) that needs resolution
        elif env_var.count('.') == 1:
            log_info(f"Resolving target minor version from TARGET_VERSION env: {env_var}")
            version = get_latest_candidate_version(dev_version=env_var)
            log_info(f"Resolved to: {version}")
            return version
        else:
            log_info(f"Using target version from TARGET_VERSION env: {env_var}")
            return env_var
    else:
        log_info("Auto-detecting target version from latest candidate...")
        version = get_latest_candidate_version()
        log_info(f"Auto-detected target version: {version}")
        return version
