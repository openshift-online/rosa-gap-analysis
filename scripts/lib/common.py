#!/usr/bin/env python3
"""Common utilities for gap analysis scripts."""

import errno
import shutil
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request


_FETCH_RETRY_WINDOW = 60
_FETCH_RETRY_DELAYS = (5, 10, 20, 20)
_TRANSIENT_HTTP_STATUSES = {408, 429, 502, 503, 504}
_TRANSIENT_TRANSPORT_ERRNOS = {
    errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
    errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ETIMEDOUT,
}


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    RESET = '\033[0m'


def log_info(message):
    """Log an info message."""
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {message}", file=sys.stderr)


def log_success(message):
    """Log a success message."""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.RESET} {message}", file=sys.stderr)


def log_warning(message):
    """Log a warning message."""
    print(f"{Colors.YELLOW}[WARNING]{Colors.RESET} {message}", file=sys.stderr)


def log_error(message):
    """Log an error message."""
    print(f"{Colors.RED}[ERROR]{Colors.RESET} {message}", file=sys.stderr)


def check_command(command):
    """Check if a command is available in PATH."""
    if not shutil.which(command):
        log_error(f"{command} not found. Please install {command}.")
        sys.exit(1)


def get_project_root():
    """Get the project root directory."""
    # Script is in scripts/lib, so project root is two levels up
    return Path(__file__).parent.parent.parent.resolve()


def _is_retryable_fetch_error(error):
    if isinstance(error, HTTPError):
        return error.code in _TRANSIENT_HTTP_STATUSES
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        return reason.errno in {socket.EAI_AGAIN, socket.EAI_NONAME}
    return isinstance(reason, TimeoutError) or (
        isinstance(reason, OSError) and reason.errno in _TRANSIENT_TRANSPORT_ERRNOS
    )


def fetch_url(url, timeout=30):
    """
    Fetch bytes with up to five attempts in a 60-second retry window.

    Retry selected transport/DNS errors and HTTP 408/429/502/503/504 only,
    waiting 5/10/20/20 seconds between attempts. Elapsed request time counts
    toward retry eligibility; no new attempt starts once the window expires.
    Each attempt's socket timeout is capped by the remaining window. This is
    not a hard deadline for an in-progress transfer. Permanent errors
    propagate immediately.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Response data as bytes

    Raises:
        HTTPError: If HTTP request fails
        URLError: If connection fails
    """
    req = Request(url, headers={'User-Agent': 'gap-analysis-script'})
    deadline = time.monotonic() + _FETCH_RETRY_WINDOW
    last_error = None
    for attempt in range(len(_FETCH_RETRY_DELAYS) + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if last_error is not None:
                raise last_error
            raise TimeoutError("Fetch retry budget exhausted")
        try:
            with urlopen(req, timeout=min(timeout, remaining)) as response:
                return response.read()
        except (URLError, OSError) as error:
            if not _is_retryable_fetch_error(error) or attempt == len(_FETCH_RETRY_DELAYS):
                raise
            delay = _FETCH_RETRY_DELAYS[attempt]
            if delay >= deadline - time.monotonic():
                raise
            if isinstance(error, HTTPError):
                error.close()
            last_error = error
            log_warning(f"Retrying fetch after {error} in {delay}s (attempt {attempt + 2})")
            time.sleep(delay)


def is_pre_ga_version(version):
    """Check if a version string is pre-GA (alpha, beta, nightly)."""
    pre_ga_markers = ['-alpha.', '-beta.', '-nightly']
    return any(marker in version for marker in pre_ga_markers)


def is_version_5x(minor_version):
    """Check if minor version is 5.x or higher (AWS/STS-only, no GCP/WIF)."""
    try:
        return int(minor_version.split('.')[0]) >= 5
    except (ValueError, IndexError):
        return False


def check_yaml_installed():
    """Check if PyYAML is installed and exit if not."""
    try:
        import yaml
    except ImportError:
        log_error("PyYAML is not installed. Install it with: pip install pyyaml")
        sys.exit(1)
