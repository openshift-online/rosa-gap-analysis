"""Regression tests for major-aware stable stream resolution (shell resolver).

scripts/gap-all.sh — the script Prow actually runs — sources
scripts/lib/openshift-releases.sh, so the shell copy of the resolver needs the
same coverage as the Python one. These tests drive the real functions through
bash with the accepted-streams cache pre-seeded from a fixture, so no API is
contacted.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.accepted_streams import (
    ACCEPTED_STREAMS,
    ACCEPTED_STREAMS_AT_GA,
    ACCEPTED_STREAMS_EMPTY_5,
    as_json,
)

ROOT = Path(__file__).resolve().parents[1]
RELEASES_LIB = ROOT / "scripts" / "lib" / "openshift-releases.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None,
    reason="shell resolver tests require bash and jq",
)


def run_resolver(call, streams=ACCEPTED_STREAMS, ga_version=None):
    """Run one resolver function with the accepted-streams cache pre-seeded.

    When ga_version is given, the Sippy lookup is stubbed too, so the whole
    resolution runs offline. Returns (returncode, stdout, stderr).
    """
    ga_stub = f'get_latest_ga_version() {{ echo "{ga_version}"; }}' if ga_version else ""
    # gap-all.sh runs under `set -euo pipefail`; use the same flags so the tests
    # exercise the real abort-on-failing-command-substitution behaviour.
    script = f"""
set -euo pipefail
source "{RELEASES_LIB}"
_ACCEPTED_STREAMS_CACHE="$(cat)"
{ga_stub}
{call}
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        input=as_json(streams),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr


# Minimal release-stream tag payloads, keyed by the stream the URL asks for.
# `5-stable` deliberately lists the RC first so a missing RC filter is visible.
_TAG_PAYLOADS = {
    "4-stable": '{"tags":[{"name":"4.22.21","pullSpec":"ps-4.22.21"}]}',
    "5-stable": '{"tags":[{"name":"5.0.0-rc.8","pullSpec":"ps-rc8"},'
                '{"name":"5.0.1","pullSpec":"ps-5.0.1"}]}',
    "5-dev-preview": '{"tags":[{"name":"5.1.0-ec.1","pullSpec":"ps-5.1.0-ec.1"}]}',
}


def run_resolver_offline_http(call, ga_version, sippy_releases=("4.22", "5.0", "5.1")):
    """Run a resolver that reaches the tags/Sippy HTTP endpoints, with _curl_with_retry
    stubbed. Echoes each requested URL to stderr so the test can assert which stream
    was consulted. Returns (returncode, stdout, stderr).
    """
    cases = "\n".join(
        f'        *{stream}/tags*) echo {payload!r} ;;' for stream, payload in _TAG_PAYLOADS.items()
    )
    sippy = json.dumps({"releases": list(sippy_releases)})
    script = f"""
set -euo pipefail
source "{RELEASES_LIB}"
get_latest_ga_version() {{ echo "{ga_version}"; }}
_curl_with_retry() {{
    echo "URL>$1" >&2
    case "$1" in
        *sippy*) echo {sippy!r} ;;
{cases}
        *) echo '{{"tags":[]}}' ;;
    esac
}}
{call}
"""
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr


# --- stream selection -------------------------------------------------------

def test_stable_stream_follows_major():
    rc, out, _ = run_resolver(
        'stable_stream_for_version 4.21; stable_stream_for_version 5.0.1; '
        'dev_preview_stream_for_version 5.1'
    )
    assert rc == 0
    assert out.splitlines() == ["4-stable", "5-stable", "5-dev-preview"]


# --- get_previous_z_stream_version -----------------------------------------

def test_previous_z_stream_resolves_5x_from_5_stable():
    """Regression for the nightly-5-0 periodic: GA=5.0 took the z-stream path and
    searched the hardcoded 4-stable, failing with 'No stable versions found for 5.0.x'."""
    rc, out, err = run_resolver("get_previous_z_stream_version 5.0")
    assert rc == 0, err
    assert out == "5.0.0"


def test_previous_z_stream_preserves_4x_behavior():
    rc, out, err = run_resolver("get_previous_z_stream_version 4.22")
    assert rc == 0, err
    assert out == "4.22.20"


def test_previous_z_stream_ignores_rc_builds_at_ga():
    """Only 5.0.0 has shipped: the 5.0.0-rc.* builds in 5-stable are not z-streams."""
    rc, out, err = run_resolver(
        "get_previous_z_stream_version 5.0", streams=ACCEPTED_STREAMS_AT_GA
    )
    assert rc == 0, err
    assert out == "SKIP"


def test_previous_z_stream_errors_when_stream_missing():
    rc, _, err = run_resolver(
        "get_previous_z_stream_version 6.0", streams=ACCEPTED_STREAMS_EMPTY_5
    )
    assert rc == 1
    assert "No stable versions found for 6.0.x" in err
    assert "6-stable" in err
    assert "is not present" in err


def test_previous_z_stream_errors_when_line_absent_from_existing_stream():
    rc, _, err = run_resolver("get_previous_z_stream_version 5.4")
    assert rc == 1
    assert "No stable versions found for 5.4.x" in err
    assert "5-stable holds 4 accepted version(s)" in err
    assert "5.0.1" in err


# --- get_latest_stable_version ---------------------------------------------

def test_latest_stable_resolves_requested_major():
    rc, out, err = run_resolver("get_latest_stable_version 5.0")
    assert rc == 0, err
    assert out == "5.0.1"


def test_latest_stable_preserves_4x_behavior():
    rc, out, err = run_resolver("get_latest_stable_version 4.21")
    assert rc == 0, err
    assert out == "4.21.30"


def test_latest_stable_excludes_rc_builds():
    rc, out, err = run_resolver(
        "get_latest_stable_version 5.0", streams=ACCEPTED_STREAMS_AT_GA
    )
    assert rc == 0, err
    assert out == "5.0.0"


def test_latest_stable_errors_on_empty_stream():
    rc, _, err = run_resolver(
        "get_latest_stable_version 5.0", streams=ACCEPTED_STREAMS_EMPTY_5
    )
    assert rc == 1
    assert "from 5-stable accepted stream" in err
    assert "5-stable holds 0 accepted version(s)" in err


# --- baseline/target precedence --------------------------------------------

def test_baseline_priority_prefers_stable_5x():
    rc, out, err = run_resolver("get_latest_version_baseline_priority 5.0")
    assert rc == 0, err
    assert out == "5.0.1"


def test_target_priority_falls_back_to_dev_preview_ec():
    rc, out, err = run_resolver("get_latest_version_target_priority 5.1")
    assert rc == 0, err
    assert out == "5.1.0-ec.1"


# --- get_latest_candidate_version ------------------------------------------

def test_latest_candidate_keeps_ga_major():
    """Regression: the dev line was built as "4.${ga_minor+1}", so GA=5.0 searched 4.1."""
    rc, out, err = run_resolver("get_latest_candidate_version", ga_version="5.0")
    assert rc == 0, err
    assert out == "5.1.0-ec.1"


def test_latest_candidate_preserves_4x_behavior():
    rc, out, err = run_resolver("get_latest_candidate_version", ga_version="4.22")
    assert rc == 0, err
    assert out == "4.23.0-ec.2"


def test_latest_candidate_prefers_rc_from_stable_over_ec():
    streams = {
        "5-stable": ["5.1.0-rc.2", "5.1.0-rc.1"],
        "5-dev-preview": ["5.1.0-ec.1"],
    }
    rc, out, err = run_resolver(
        "get_latest_candidate_version", streams=streams, ga_version="5.0"
    )
    assert rc == 0, err
    assert out == "5.1.0-rc.2"


def test_latest_candidate_reports_both_streams_on_failure():
    rc, _, err = run_resolver(
        "get_latest_candidate_version", streams=ACCEPTED_STREAMS_AT_GA, ga_version="5.0"
    )
    assert rc == 1
    assert "no RC in 5-stable, no EC in 5-dev-preview" in err
    assert "5-dev-preview is not present" in err


# --- resolve_openshift_version (the entry point gap-all.sh calls) ----------

def test_resolve_version_5_0_after_ga():
    """End-to-end for the failing periodic: OPENSHIFT_VERSION=5.0 with GA=5.0.

    gap-all.sh calls resolve_openshift_version and runs under `set -e`, so the
    non-zero return seen in the job aborted the whole run.
    """
    rc, out, err = run_resolver("resolve_openshift_version 5.0", ga_version="5.0")
    assert rc == 0, err
    assert out == "5.0.0 5.0.1"
    assert "using z-stream comparison" in err


def test_resolve_version_4x_z_stream_unchanged():
    rc, out, err = run_resolver("resolve_openshift_version 4.22", ga_version="4.22")
    assert rc == 0, err
    assert out == "4.22.20 4.22.21"


def test_resolve_version_4x_pre_ga_cross_minor_unchanged():
    rc, out, err = run_resolver("resolve_openshift_version 4.23", ga_version="4.22")
    assert rc == 0, err
    assert out == "4.22.21 4.23.0-ec.2"


def test_resolve_version_5_1_baseline_line_has_no_stable_release():
    """4.23 → 5.1 spans majors, and 4.23 has not shipped a stable release yet.

    The baseline must be looked up in 4-stable (not the GA major's 5-stable) and,
    finding nothing there, fail loudly with diagnostics rather than silently
    handing back a 5.0.x baseline. This matches openshift_releases.py.
    """
    rc, _, err = run_resolver("resolve_openshift_version 5.1", ga_version="5.0")
    assert rc == 1
    assert "for 4.23.x from 4-stable accepted stream" in err
    assert "4-stable holds 7 accepted version(s)" in err
    assert "5-stable" not in err


def test_resolve_version_skips_freshly_ga_4x_line():
    """A 4.y line whose only other 4-stable entries are its own RCs has no previous
    z-stream, so the run is skipped instead of comparing 4.22.0 against 4.22.0-rc.4."""
    streams = {"4-stable": ["4.22.0", "4.22.0-rc.4", "4.22.0-rc.3", "4.21.30"]}
    rc, out, err = run_resolver(
        "resolve_openshift_version 4.22", streams=streams, ga_version="4.22"
    )
    assert rc == 0, err
    assert out == "SKIP SKIP"


def test_resolve_version_skips_when_single_z_stream():
    rc, out, err = run_resolver(
        "resolve_openshift_version 5.0", streams=ACCEPTED_STREAMS_AT_GA, ga_version="5.0"
    )
    assert rc == 0, err
    assert out == "SKIP SKIP"


# --- diagnostics ------------------------------------------------------------

def test_failure_diagnostic_is_bounded_and_non_sensitive():
    # Newest first, as the accepted API returns them
    streams = {"5-stable": [f"5.0.{i}" for i in range(39, -1, -1)]}
    rc, _, err = run_resolver("get_previous_z_stream_version 5.9", streams=streams)
    assert rc == 1
    assert "5-stable holds 40 accepted version(s)" in err
    assert "5.0.39" in err  # newest is reported
    assert "5.0.29" not in err  # capped at the 10 newest
    # The stream contents are sampled, not dumped
    assert err.count("5.0.") <= 11


# --- HTTP-backed resolvers on gap-all.sh's auto-detect path ----------------

def test_latest_dev_version_keeps_ga_major():
    """Regression: the dev line was built as "4.${ga_minor+1}", so GA=5.0 asked for 4.1."""
    rc, out, err = run_resolver_offline_http("get_latest_dev_version", ga_version="5.0")
    assert rc == 0, err
    assert out == "5.1"


def test_latest_dev_version_preserves_4x_behavior():
    rc, out, err = run_resolver_offline_http(
        "get_latest_dev_version", ga_version="4.22", sippy_releases=("4.22", "4.23")
    )
    assert rc == 0, err
    assert out == "4.23"


def test_stable_pullspec_uses_major_stream_and_skips_rc():
    """gap-all.sh:260-261 pairs get_latest_stable_version with this function, so both
    must pick the same release: the major's own stable stream, RC builds excluded."""
    rc, out, err = run_resolver_offline_http("get_latest_stable_pullspec", ga_version="5.0")
    assert rc == 0, err
    assert "releasestream/5-stable/tags" in err
    assert "releasestream/4-stable/tags" not in err
    assert out == "ps-5.0.1"  # not ps-rc8, which the payload lists first


def test_stable_pullspec_preserves_4x_behavior():
    rc, out, err = run_resolver_offline_http("get_latest_stable_pullspec", ga_version="4.22")
    assert rc == 0, err
    assert "releasestream/4-stable/tags" in err
    assert out == "ps-4.22.21"


def test_candidate_pullspec_uses_major_streams():
    rc, out, err = run_resolver_offline_http("get_latest_candidate_pullspec", ga_version="5.0")
    assert rc == 0, err
    assert "releasestream/5-stable/tags" in err
    assert "releasestream/5-dev-preview/tags" in err
    assert "releasestream/4-" not in err
    assert out == "ps-5.1.0-ec.1"


# --- gap-all.sh consumer path ----------------------------------------------

GAP_ALL_CONSUMER = """
resolve_result=$(resolve_openshift_version "5.0")
echo "REACHED_NEXT_STEP"
echo "BASELINE=$(echo "$resolve_result" | awk '{print $1}')"
echo "TARGET=$(echo "$resolve_result" | awk '{print $2}')"
"""


def test_consumer_path_produces_the_expected_5_0_comparison():
    """The exact shape of the live 5-stable stream must yield a real comparison.

    Mirrors scripts/gap-all.sh:5,9,190: `set -euo pipefail`, source the library,
    assign from resolve_openshift_version. The fix must not make the reported
    failure "pass" by skipping.
    """
    rc, out, err = run_resolver(
        GAP_ALL_CONSUMER,
        streams={"5-stable": ["5.0.1", "5.0.0", "5.0.0-rc.8"]},
        ga_version="5.0",
    )
    assert rc == 0, err
    assert "REACHED_NEXT_STEP" in out
    assert "BASELINE=5.0.0" in out
    assert "TARGET=5.0.1" in out
    assert "SKIP" not in out


def test_consumer_path_still_fails_when_the_line_has_no_stable_release():
    """A line present in the streams but with no stable release is a real error:
    the job must go red, not green and not SKIP. Guards the `set -e` handling."""
    rc, out, err = run_resolver(
        GAP_ALL_CONSUMER,
        streams={
            "5-stable": ["5.0.0-rc.8", "5.0.0-rc.7"],
            "5.0.0-0.nightly": ["5.0.0-0.nightly-2026-11-01"],
        },
        ga_version="5.0",
    )
    assert rc != 0
    assert "REACHED_NEXT_STEP" not in out
    assert "No stable versions found for 5.0.x" in err
    assert "5-stable holds 2 accepted version(s)" in err
