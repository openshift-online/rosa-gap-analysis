#!/usr/bin/env python3
"""Common utilities for gap analysis scripts."""

import errno
import shutil
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen, Request


_FETCH_RETRY_DELAYS = (5, 10, 20, 20)
_FETCH_RETRY_BUDGET = 60


def fetch_error_detail(error):
    """Describe errors without arbitrary messages, URLs, bodies or resolver addresses."""
    reason = error.reason if isinstance(error, URLError) and not isinstance(error, HTTPError) else error
    detail = type(reason).__name__
    if isinstance(reason, HTTPError):
        return f"{detail} status={reason.code}"
    if isinstance(reason, socket.gaierror):
        names = {socket.EAI_NONAME: 'EAI_NONAME', socket.EAI_AGAIN: 'EAI_AGAIN'}
        return f"{detail} errno={reason.errno} ({names.get(reason.errno, 'DNS error')})"
    if isinstance(reason, OSError):
        return f"{detail} errno={reason.errno}"
    if hasattr(reason, 'lineno') and hasattr(reason, 'colno'):
        return f"{detail} line={reason.lineno} column={reason.colno}"
    return detail


def _is_retryable_fetch_error(error):
    if isinstance(error, HTTPError):
        return error.code in {408, 429, 502, 503, 504}
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        return reason.errno in {socket.EAI_NONAME, socket.EAI_AGAIN}
    return isinstance(reason, TimeoutError) or (
        isinstance(reason, OSError) and reason.errno in {
            errno.ECONNRESET, errno.ECONNABORTED, errno.ECONNREFUSED, errno.ETIMEDOUT,
        }
    )


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


def fetch_url(url, timeout=30):
    """
    Fetch bytes with at most five attempts within a 60-second retry budget.

    Retry selected DNS/transport failures and HTTP 408/429/502/503/504.
    Other HTTP, TLS and parsing errors fail immediately. Request time counts
    toward the monotonic budget; sleeps and socket timeouts are capped by it.
    This bounds retry scheduling, not an in-progress DNS lookup or transfer:
    Python's resolver and per-operation socket timeout are not hard deadlines.
    Diagnostics identify only the endpoint host, never URL paths or queries.

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
    endpoint = repr(urlsplit(url).hostname)
    started = time.monotonic()
    last_error = None
    for attempt in range(1, len(_FETCH_RETRY_DELAYS) + 2):
        elapsed = time.monotonic() - started
        remaining = _FETCH_RETRY_BUDGET - elapsed
        evidence = (f"endpoint={endpoint} attempt={attempt}/5 "
                    f"elapsed={elapsed:.3f}s budget={_FETCH_RETRY_BUDGET}s")
        if remaining <= 0:
            log_error(f"Fetch exhausted before next attempt: {evidence} "
                      f"completed_attempts={attempt - 1} error={fetch_error_detail(last_error)}")
            if last_error is not None:
                raise last_error
            raise TimeoutError("Fetch retry budget exhausted before first attempt")
        try:
            with urlopen(req, timeout=min(timeout, remaining)) as response:
                data = response.read()
            if attempt > 1:
                log_info(f"Fetch succeeded: endpoint={endpoint} attempt={attempt}/5 "
                         f"elapsed={time.monotonic() - started:.3f}s budget={_FETCH_RETRY_BUDGET}s")
            return data
        except (URLError, OSError) as error:
            last_error = error
            if isinstance(error, HTTPError):
                error.close()
            elapsed = time.monotonic() - started
            evidence = (f"endpoint={endpoint} attempt={attempt}/5 "
                        f"elapsed={elapsed:.3f}s budget={_FETCH_RETRY_BUDGET}s "
                        f"error={fetch_error_detail(error)}")
            delay = _FETCH_RETRY_DELAYS[attempt - 1] if attempt <= len(_FETCH_RETRY_DELAYS) else None
            if (not _is_retryable_fetch_error(error) or delay is None
                    or delay >= _FETCH_RETRY_BUDGET - elapsed):
                log_error(f"Fetch failed (no further retries): {evidence}")
                raise
            log_warning(f"Fetch retry scheduled: {evidence} delay={delay}s")
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
