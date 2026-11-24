"""Regression tests for major-aware stable stream resolution (shell resolver).

scripts/gap-all.sh — the script Prow actually runs — sources
scripts/lib/openshift-releases.sh, so the shell copy of the resolver needs the
same coverage as the Python one. These tests drive the real functions through
bash with the accepted-streams cache pre-seeded from a fixture, with
_curl_with_retry stubbed, or with the `curl` binary itself stubbed, so no API
is contacted.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.fixtures.accepted_streams import (
    ACCEPTED_STREAMS,
    ACCEPTED_STREAMS_AT_GA,
    ACCEPTED_STREAMS_EMPTY_5,
    as_json,
)
from tests.fixtures.sippy_releases import (
    MIXED_PRODUCT_LATEST_GA,
    MIXED_PRODUCT_RELEASES,
    NO_OCP_GA_RELEASES,
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


# --- get_latest_ga_version: fetch stage vs parse stage ----------------------
#
# These drive the real get_latest_ga_version with the `curl` BINARY stubbed
# rather than _curl_with_retry, so the genuine retry and logging layer runs and
# the fetch/parse split is actually exercised. Nothing contacts the network and
# no credentials are involved.

# Minimum set of external commands the library needs once PATH is sandboxed.
_SANDBOX_BINARIES = ("bash", "cat", "dirname", "grep", "mktemp", "rm", "sleep", "tr", "wc")

# Printed by the harness so a test can tell a resolved version from a failure.
_GA_CALL = """
if ga=$(get_latest_ga_version); then
    echo "GA=$ga"
else
    echo "RC=$?"
fi
"""


def _write_curl_stub(bindir, sippy_body, streams_body, http_code):
    """Install a `curl` that answers from fixtures instead of the network.

    Honours curl's `-o <file>` and writes the HTTP status to stdout, which is
    the contract _curl_with_retry relies on (`-w '%{http_code}' -o "$tmpfile"`).
    """
    sippy_file = bindir / "_sippy_body"
    sippy_file.write_text(sippy_body)
    streams_file = bindir / "_streams_body"
    streams_file.write_text(streams_body)

    stub = bindir / "curl"
    stub.write_text(
        "#!/bin/bash\n"
        'out=""; prev=""; url=""\n'
        'for arg in "$@"; do\n'
        '  if [ "$prev" = "-o" ]; then out="$arg"; fi\n'
        '  case "$arg" in https://*) url="$arg" ;; esac\n'
        '  prev="$arg"\n'
        "done\n"
        'case "$url" in\n'
        f"  *sippy*) cat {shlex.quote(str(sippy_file))} > \"$out\" ;;\n"
        f"  *)       cat {shlex.quote(str(streams_file))} > \"$out\" ;;\n"
        "esac\n"
        f"printf '%s' '{http_code}'\n"
    )
    stub.chmod(0o755)


def run_with_stubbed_curl(
    sippy_body,
    call=_GA_CALL,
    streams_body=None,
    http_code="200",
    with_jq=True,
):
    """Run `call` against the real library with the curl binary stubbed.

    with_jq=False sandboxes PATH down to _SANDBOX_BINARIES plus the stub, so jq
    really is absent and the shell really does produce exit 127.
    Returns (returncode, stdout, stderr).
    """
    with tempfile.TemporaryDirectory() as tmp:
        bindir = Path(tmp)
        _write_curl_stub(
            bindir, sippy_body, streams_body if streams_body is not None else "{}", http_code
        )

        if with_jq:
            path = f"{bindir}{os.pathsep}{os.environ['PATH']}"
        else:
            for name in _SANDBOX_BINARIES:
                located = shutil.which(name)
                if located is None:
                    pytest.skip(f"sandboxed PATH needs {name}")
                (bindir / name).symlink_to(located)
            path = str(bindir)

        # Shadow sleep so the retry *waits* are skipped. The retry COUNT is
        # untouched; the tests below assert all three attempts still happen.
        script = f"""
set -euo pipefail
source "{RELEASES_LIB}"
sleep() {{ :; }}
{call}
"""
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            # Minimal environment: no ambient tokens, no BASH_ENV.
            env={"PATH": path, "HOME": tmp, "LC_ALL": "C"},
        )
    return proc.returncode, proc.stdout.strip(), proc.stderr


def test_ga_version_orders_minors_numerically_not_lexically():
    """4.9 sorts after 4.20 lexically; the numeric sort must still win."""
    body = json.dumps({"ga_dates": {"4.9": "d", "4.20": "d", "4.10": "d"}})
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "GA=4.20"
    assert "Failed to fetch" not in err


def test_ga_version_reports_non_json_response():
    rc, out, err = run_with_stubbed_curl("<html><title>Bad Gateway</title></html>")
    assert rc == 0, err  # the harness swallows the non-zero; the function returned 1
    assert out == "RC=1"
    assert "Failed to fetch latest GA version from Sippy API" in err
    assert "response is not a single valid JSON document" in err
    # jq's own parse error can quote the offending bytes, so it must stay hidden.
    assert "jq:" not in err
    assert len([line for line in err.splitlines() if line.strip()]) == 2


def test_ga_version_reports_absent_ga_dates():
    body = json.dumps({"releases": ["4.20", "4.21"]})
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1"
    assert "response has no ga_dates field" in err
    # The byte count is a real measurement, not a placeholder.
    assert f"({len(body)} byte(s))" in err


def test_ga_version_reports_wrong_ga_dates_type():
    rc, out, err = run_with_stubbed_curl(json.dumps({"ga_dates": ["4.20"]}))
    assert rc == 0, err
    assert out == "RC=1"
    assert "ga_dates is JSON array, expected object" in err


def test_ga_version_reports_non_object_root():
    rc, out, err = run_with_stubbed_curl(json.dumps(["4.20", "4.21"]))
    assert rc == 0, err
    assert out == "RC=1"
    assert "response root is JSON array, expected object" in err


def test_ga_version_reports_empty_ga_dates():
    rc, out, err = run_with_stubbed_curl(json.dumps({"ga_dates": {}}))
    assert rc == 0, err
    assert out == "RC=1"
    assert "ga_dates is an empty object" in err


def test_ga_version_reports_no_ocp_release_in_ga_dates():
    """ga_dates covers every Sippy product, so a populated map need not hold an
    OCP release. That is a failure, and one the diagnostic must name as such
    rather than blaming the key format."""
    body = json.dumps(NO_OCP_GA_RELEASES)
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1", "another product's release must not be returned as the OCP GA"
    assert "ga_dates holds 2 key(s), none of them a GA'd OCP version" in err
    assert "logging-6.6" not in err and "quay" not in err


# --- get_latest_ga_version: OCP-only selection ------------------------------
#
# Regression for periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-
# nightly-4-19: Sippy fills the deprecated ga_dates for every product it
# tracks, so logging-6.6 (product "OCP Logging") joined the OCP minors there.
# Sorting the whole key set as OpenShift versions fed "logging-6" to tonumber,
# and the job failed with "at least one of which is not a numeric version"
# although every OCP release in the payload was perfectly well formed.

def test_ga_version_ignores_other_products():
    """The live mix: OCP 4.19/5.0, OCP Logging logging-6.6, OKD 5.0-okd."""
    rc, out, err = run_with_stubbed_curl(json.dumps(MIXED_PRODUCT_RELEASES))
    assert rc == 0, err
    assert out == f"GA={MIXED_PRODUCT_LATEST_GA}"
    assert "Failed to fetch" not in err


def test_ga_version_selects_by_product_not_key_shape():
    """A non-OCP release with a version-shaped key must still be excluded,
    which only the product metadata can decide."""
    body = json.dumps({
        "ga_dates": {"4.19": "2025-06-17", "9.9": "2026-01-01"},
        "release_attrs": {"4.19": {"product": "OCP"}, "9.9": {"product": "OKD"}},
    })
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "GA=4.19"


def test_ga_version_tolerates_an_unreadable_key_beside_a_good_one():
    """An entry the resolver cannot read is skipped, not treated as a veto on
    the rest of the map — the exact regression the nightly hit."""
    body = json.dumps({"ga_dates": {"four-twenty": "d", "4.21": "d"}})
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "GA=4.21"


def test_ga_version_accepts_a_payload_without_release_attrs():
    """An older Sippy has no release_attrs; the numeric guard alone decides,
    exactly as it did before the product filter existed."""
    body = json.dumps({"ga_dates": {"4.19": "d", "5.0": "d"}})
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "GA=5.0"


@pytest.mark.parametrize("release_attrs", [
    "nope",                      # wrong type for the whole map
    {"4.19": "nope"},            # wrong type for one release
    {"4.19": {}},                # present, but no product named
    {"4.19": {"product": None}},
])
def test_ga_version_survives_an_unusable_release_attrs(release_attrs):
    """release_attrs the filter cannot read must not break selection: fall back
    to the numeric guard rather than failing the whole resolution."""
    body = json.dumps({"ga_dates": {"4.19": "d"}, "release_attrs": release_attrs})
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "GA=4.19"


def test_ga_version_obeys_a_product_that_is_present_but_falsy():
    """Only an ABSENT product defaults to OCP. `false` is a stated product, not
    an unset one, and jq's `//` would quietly read it as unset — which is the
    one place the two resolver copies could drift apart."""
    body = json.dumps({
        "ga_dates": {"4.19": "d"},
        "release_attrs": {"4.19": {"product": False}},
    })
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1"
    assert "none of them a GA'd OCP version" in err


@pytest.mark.parametrize("extra_keys", [
    # "" survives `split(".") | all(...)` vacuously, so the empty split result
    # has to be rejected explicitly.
    ["", "4.", "4.x"],
    # Non-ASCII digits: jq's explode/48-57 test rejects these, and the Python
    # twin needs an isascii() guard to agree. Pinned on both sides.
    ["４.１９", "4.1²"],
])
def test_ga_version_skips_degenerate_keys(extra_keys):
    """Mirrors the Python suite's unexpected-payload table."""
    ga_dates = {"4.19": "d"}
    ga_dates.update({key: "d" for key in extra_keys})
    rc, out, err = run_with_stubbed_curl(json.dumps({"ga_dates": ga_dates}))
    assert rc == 0, err
    assert out == "GA=4.19"


def test_ga_version_reports_blank_response_body():
    """A whitespace-only 200 clears _curl_with_retry's non-empty check, and jq
    exits 0 on it — so the empty-version guard is the only thing that fails it."""
    rc, out, err = run_with_stubbed_curl("   \n  ")
    assert rc == 0, err
    assert out == "RC=1"
    assert "response body is blank" in err
    # Must not be mislabelled as a parse error when jq reported success.
    assert "not valid JSON" not in err


def test_ga_version_rejects_a_payload_jq_only_partially_parsed():
    """jq streams values as it reads them, so it prints a type for the leading
    document and only then fails on the trailing junk. Output alone therefore
    does not prove the body parsed; the probe's exit status must decide.

    The payload must be rejected AND classified as invalid JSON -- `4.21` is a
    perfectly good numeric key, so blaming the keys would misdirect triage.
    """
    rc, out, err = run_with_stubbed_curl('{"ga_dates":{"4.21":"d"}} trailing garbage')
    assert rc == 0, err
    assert out == "RC=1", "a partially parsed payload must not yield a GA version"
    assert "could not read ga_dates" in err
    assert "response is not a single valid JSON document" in err
    assert "numeric version" not in err, "must not be blamed on the key format"
    assert "jq:" not in err


def test_ga_version_rejects_a_valid_multi_document_response():
    """A JSON *stream* parses cleanly, so the extract filter runs once per
    document and emits one version per line. Without a single-document gate
    that multi-line value is returned as if it were a GA version.
    """
    body = '{"ga_dates":{"4.20":"d"}} {"ga_dates":{"4.21":"d"}}'
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1", "a multi-document response must not yield a GA version"
    assert "response holds 2 JSON document(s), expected exactly 1" in err
    # Fail-closed: neither per-document version reaches stdout or the log.
    assert "4.20" not in err and "4.21" not in err
    assert "jq:" not in err
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 2


@pytest.mark.parametrize(
    "literal", ["Infinity", "-Infinity", "NaN", "nan", "1e400"]
)
def test_ga_version_rejects_a_payload_with_a_non_finite_number(literal):
    """jq's parser is a superset of JSON: it accepts the bare literals
    Infinity, -Infinity and NaN. Such a body parses with exit 0 as a single
    document, so the exit status alone cannot stand in for "this was JSON"
    and the resolver would return a version from a payload JSON forbids.

    1e400 is valid JSON grammar but overflows a double and reads back as
    infinite, so it is rejected on the same ground: a number that cannot be
    read back faithfully is not one to resolve a version from.
    """
    body = '{"ga_dates":{"4.21":"d"},"extra":' + literal + "}"
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1", f"a payload carrying {literal} must not yield a GA version"
    assert "could not read ga_dates" in err
    assert "non-finite number" in err
    # `4.21` is a perfectly good key, so blaming the key format would
    # misdirect triage exactly as the partial-parse branch once did.
    assert "numeric version" not in err
    assert "4.21" not in err
    assert "jq:" not in err
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 2


def test_ga_version_rejects_a_non_finite_number_hidden_by_a_duplicate_key():
    """Object construction is lossy: on a duplicate key the later value
    replaces the earlier one. A guard that walks the *built* value therefore
    sees a wholly finite object here and lets the body through, even though
    `Infinity` was parsed. The scalars must be checked as parse events, before
    construction discards them.
    """
    body = '{"ga_dates":{"4.21":"d"},"extra":Infinity,"extra":0}'
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1", "a discarded non-finite value must still reject the body"
    assert "non-finite number" in err
    assert "4.21" not in err
    assert "jq:" not in err


def test_ga_version_rejects_a_non_finite_number_in_a_nested_duplicate_key():
    """Same loss one level down, where the surviving value is also finite."""
    body = '{"ga_dates":{"4.21":"d"},"meta":{"x":NaN,"x":1}}'
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1"
    assert "non-finite number" in err


def test_ga_version_rejects_a_non_finite_number_early_in_a_large_response():
    """Regression for a SIGPIPE fail-open.

    A probe that stops at the first hit lets jq exit while the writer still
    has data to push. The writer takes SIGPIPE, and under `pipefail` -- which
    scripts/gap-all.sh sets -- the pipeline reports 141 even though the
    detection succeeded, so the caller reads it as "nothing found". Small
    fixtures hide this entirely: they fit in the pipe buffer, so the writer
    finishes before jq exits. The padding here is what exposes it.
    """
    body = (
        '{"ga_dates":{"4.21":"d"},"extra":Infinity,"pad":"'
        + "x" * (2 * 1024 * 1024)
        + '"}'
    )
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1", "a non-finite number must be caught regardless of body size"
    assert "non-finite number" in err


def test_ga_version_accepts_a_large_clean_response():
    """The other half: padding alone must not trip the gate."""
    body = json.dumps({"ga_dates": {"4.20": "d", "4.21": "d"}, "pad": "x" * (2 * 1024 * 1024)})
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "GA=4.21"
    assert "non-finite" not in err


def test_ga_version_still_accepts_finite_numbers_in_the_payload():
    """The non-finite gate must not reject ordinary numeric fields: the same
    shape with a finite number has to resolve exactly as before.
    """
    body = json.dumps(
        {"ga_dates": {"4.20": "d", "4.21": "d"}, "extra": 1, "ratio": 1.5e10}
    )
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "GA=4.21"
    assert "Failed to fetch" not in err
    assert "non-finite" not in err


def test_ga_version_rejects_a_response_carrying_a_raw_nul_byte():
    """Bash command substitution silently drops NUL bytes, so a 200 response
    holding a valid GA object plus a raw NUL would be captured as a clean
    object and pass every parse check — the resolver would resolve a version
    from a body the server never sent. The bytes are counted on the response
    file, before the capture, so the response is rejected instead.
    """
    body = '{"ga_dates":{"4.21":"d"}}\x00'
    rc, out, err = run_with_stubbed_curl(body)
    assert rc == 0, err
    assert out == "RC=1", "a NUL-carrying response must not yield a GA version"
    # Named as a count, never as body bytes, and the snippet is dropped.
    assert "RESPONSE_NUL_BYTES=1" in err
    assert "4.21" not in err
    # Rejected at the fetch stage, so the retry layer stays in charge.
    for attempt in (1, 2, 3):
        assert f"API request failed (attempt {attempt}/3)" in err
    assert "returned no usable response" in err


def test_curl_retry_returns_a_clean_body_unchanged():
    """Tripwire for the NUL counting added above: the ordinary success path
    must still hand back the exact bytes, with no measurement side effect.
    """
    body = json.dumps({"ga_dates": {"4.21": "2025-01-01"}})
    rc, out, err = run_with_stubbed_curl(
        body, call='_curl_with_retry "${SIPPY_API}"'
    )
    assert rc == 0, err
    assert out == body
    assert "API request failed" not in err


def test_ga_version_reports_unusable_jq():
    body = json.dumps({"ga_dates": {"4.21": "d"}})
    rc, out, err = run_with_stubbed_curl(body, with_jq=False)
    assert rc == 0, err
    assert out == "RC=1"
    assert "jq is unavailable or not executable (exit 127)" in err
    # A missing parser must not be misreported as a bad payload.
    assert "not valid JSON" not in err
    # Tripwire: the sandboxed PATH must be complete, so the only thing missing
    # is jq. Without this, a second missing binary would pass unnoticed.
    assert "command not found" not in err


def test_ga_version_separates_transport_failure_from_parse_failure():
    """A non-2xx response keeps _curl_with_retry's existing per-attempt logging
    and is classified as a request failure, never as a payload problem.

    Only the request/parse split is asserted here. The content of
    _curl_with_retry's own HTTP lines is its long-standing behaviour and is
    outside what this function changed.
    """
    body = json.dumps({"ga_dates": {"4.21": "d"}})
    rc, out, err = run_with_stubbed_curl(body, http_code="503")
    assert rc == 0, err
    assert out == "RC=1"
    # Retry count is unchanged: all three attempts are still reported.
    for attempt in (1, 2, 3):
        assert f"API request failed (attempt {attempt}/3)" in err
    assert "API request failed after 3 attempts" in err
    assert "returned no usable response" in err
    assert "could not read ga_dates" not in err


# One body per classification branch, each carrying the sentinel, so a body
# excerpt added to any single branch is caught rather than only the first.
_SENTINEL = "SENTINEL-must-never-reach-a-log-9f2c1b"
_SENTINEL_BODIES = {
    "not-json": f"<html>{_SENTINEL}</html>",
    "non-object-root": json.dumps([_SENTINEL]),
    "absent-ga-dates": json.dumps({"unexpected": _SENTINEL, "note": _SENTINEL}),
    "wrong-ga-dates-type": json.dumps({"ga_dates": _SENTINEL}),
    "empty-ga-dates": json.dumps({"ga_dates": {}, "note": _SENTINEL}),
    "no-ocp-release": json.dumps({"ga_dates": {_SENTINEL: "d"}}),
    # Version-shaped key, so the product value really is read by the filter.
    "non-ocp-product": json.dumps({
        "ga_dates": {"9.9": "d"},
        "release_attrs": {"9.9": {"product": _SENTINEL}},
    }),
    "trailing-garbage": json.dumps({"ga_dates": {"4.21": "d"}}) + f" {_SENTINEL}",
    "multi-document": json.dumps({"ga_dates": {"4.20": "d"}})
    + " "
    + json.dumps({"note": _SENTINEL}),
    "non-finite-number": '{"ga_dates":{"4.21":"d"},"note":"'
    + _SENTINEL
    + '","extra":Infinity}',
}


@pytest.mark.parametrize("label", sorted(_SENTINEL_BODIES))
def test_ga_version_diagnostic_never_echoes_the_response(label):
    """Every classification branch must stay free of response content."""
    rc, out, err = run_with_stubbed_curl(_SENTINEL_BODIES[label])
    assert rc == 0, err
    assert out == "RC=1"
    assert _SENTINEL not in err, f"{label} branch leaked the response body"
    assert _SENTINEL not in out
    assert "jq:" not in err, f"{label} branch leaked jq stderr"
    # Two lines only (the error marker plus one classification), both bounded.
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 2
    assert all(len(line) < 200 for line in lines)


def test_ga_version_diagnostic_is_deterministic_and_names_only_the_endpoint():
    body = json.dumps({"unexpected": _SENTINEL})
    first = run_with_stubbed_curl(body)
    second = run_with_stubbed_curl(body)
    assert first == second, "the diagnostic must not vary between runs"
    err = first[2]
    # Only the fixed endpoint is named, with no query string appended.
    assert "https://sippy.dptools.openshift.org/api/releases" in err
    assert "?" not in err


def test_safe_helpers_reject_untrusted_values():
    """The sanitizers are the whole leak defence, so pin both directions."""
    rc, out, err = run_resolver(
        "_safe_json_type object; _safe_json_type null; "
        "_safe_json_type 'object\nINJECTED [ERROR] fake'; "
        "_safe_json_type 'obj*'; _safe_json_type ''; "
        "_safe_count 42; _safe_count 0; "
        "_safe_count '7; rm -rf /'; _safe_count -1; _safe_count ''",
        streams={},
    )
    assert rc == 0, err
    assert out.splitlines() == [
        "object", "null", "unknown", "unknown", "unknown",
        "42", "0", "unknown", "unknown", "unknown",
    ]


def test_caller_path_surfaces_the_parse_classification():
    """resolve_openshift_version is what gap-all.sh calls; its step 1 failure
    must carry the new classification, not just the legacy error line."""
    rc, out, err = run_with_stubbed_curl(
        json.dumps({"releases": ["4.20"]}),
        call='if resolve_openshift_version 4.20; then echo "OK"; else echo "RC=$?"; fi',
    )
    assert out == "RC=1", err
    assert "Failed to fetch latest GA version from Sippy API" in err
    assert "response has no ga_dates field" in err


def test_caller_path_still_resolves_when_sippy_is_well_formed():
    """The split must not regress the happy path through the real HTTP stage."""
    rc, out, err = run_with_stubbed_curl(
        json.dumps({"ga_dates": {"4.22": "d", "5.0": "d"}}),
        streams_body=as_json(ACCEPTED_STREAMS),
        call=GAP_ALL_CONSUMER,
    )
    assert rc == 0, err
    assert "REACHED_NEXT_STEP" in out
    assert "BASELINE=5.0.0" in out
    assert "TARGET=5.0.1" in out


def test_caller_path_resolves_against_a_multi_product_sippy_payload():
    """End-to-end for the reported failure: gap-all.sh's own entry point, over
    a payload whose ga_dates mixes OCP, OCP Logging and OKD releases."""
    rc, out, err = run_with_stubbed_curl(
        json.dumps(MIXED_PRODUCT_RELEASES),
        streams_body=as_json(ACCEPTED_STREAMS),
        call=GAP_ALL_CONSUMER,
    )
    assert rc == 0, err
    assert "REACHED_NEXT_STEP" in out
    assert "BASELINE=5.0.0" in out
    assert "TARGET=5.0.1" in out


# --- README quick-reference parity -----------------------------------------
#
# README.md ships a curl|jq one-liner answering the same question as
# get_latest_ga_version, so a reader who runs it must get the resolver's
# answer. It once applied `// "OCP"` to the product value, which reads a
# present `false` as "absent" and so kept a release both resolvers drop.

README = ROOT / "README.md"
_README_MARKER = "# Get latest GA version from Sippy"

_JQ_HAS_REGEX = subprocess.run(
    ["jq", "-ne", '"4" | test("^[0-9]$")'], capture_output=True, check=False
).returncode == 0


def _readme_latest_ga_program():
    """Extract the jq program from the README's latest-GA quick reference."""
    text = README.read_text(encoding="utf-8")
    assert _README_MARKER in text, "README lost its latest-GA quick-reference command"
    match = re.search(r"jq -r '([^']*)'", text.split(_README_MARKER, 1)[1])
    assert match, "could not extract the jq program from the README snippet"
    return match.group(1)


def _run_jq(program, body):
    proc = subprocess.run(
        ["jq", "-r", program], input=body, capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr


def _resolver_latest_ga(body):
    """Run the shipped _JQ_OCP_GA_VERSIONS program over the same payload."""
    script = f'set -euo pipefail\nsource "{RELEASES_LIB}"\njq -r "${{_JQ_OCP_GA_VERSIONS}} | last"\n'
    proc = subprocess.run(
        ["bash", "-c", script], input=body, capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr


# Each payload names a way the two could drift apart.
_README_PARITY_PAYLOADS = {
    "live-shape": MIXED_PRODUCT_RELEASES,
    "no-ocp-release": NO_OCP_GA_RELEASES,
    "no-release-attrs": {"ga_dates": {"4.19": "d", "5.0": "d"}},
    "numeric-order": {"ga_dates": {"4.9": "d", "4.20": "d", "4.10": "d"}},
    "okd-with-version-shaped-key": {
        "ga_dates": {"4.19": "d", "9.9": "d"},
        "release_attrs": {"9.9": {"product": "OKD"}},
    },
    # The regression: `false` is a stated product, not an absent one.
    "falsy-product": {
        "ga_dates": {"4.19": "d", "9.9": "d"},
        "release_attrs": {"9.9": {"product": False}},
    },
    "null-product": {
        "ga_dates": {"4.19": "d"},
        "release_attrs": {"4.19": {"product": None}},
    },
    "unusable-release-attrs": {"ga_dates": {"4.19": "d"}, "release_attrs": "nope"},
    "unusable-entry": {"ga_dates": {"4.19": "d"}, "release_attrs": {"4.19": "nope"}},
    "degenerate-keys": {"ga_dates": {"4.19": "d", "": "d", "4.": "d", "4.x": "d"}},
}


@pytest.mark.skipif(not _JQ_HAS_REGEX, reason="README snippet needs a regex-enabled jq")
@pytest.mark.parametrize("label", sorted(_README_PARITY_PAYLOADS))
def test_readme_quick_reference_matches_the_resolver(label):
    body = json.dumps(_README_PARITY_PAYLOADS[label])

    readme_rc, readme_out, readme_err = _run_jq(_readme_latest_ga_program(), body)
    resolver_rc, resolver_out, resolver_err = _resolver_latest_ga(body)

    assert readme_rc == 0, f"README snippet failed on {label}: {readme_err}"
    assert resolver_rc == 0, f"resolver failed on {label}: {resolver_err}"
    assert readme_out == resolver_out, (
        f"README snippet and resolver disagree on {label}: "
        f"{readme_out!r} vs {resolver_out!r}"
    )
