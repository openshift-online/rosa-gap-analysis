"""Offline regression tests for ci/lib/download-with-retry.sh.

The build root used by Prow (ci/Containerfile) failed when a single HTTP 504 was
returned while downloading the ROSA CLI zip, so the nightly gap analysis never
executed. These tests pin the retry semantics of the downloader that replaced the
bare `curl -fsSL` calls.

No network access is used: `curl` is replaced on PATH by a stub driven by a
scripted outcome plan. The stub deliberately honours the flags the script passes
(`--fail`, `--location`, `--output`, `--write-out`) and models real curl's
behaviour for each, so dropping any of them from the script fails a test rather
than passing silently.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ci" / "lib" / "download-with-retry.sh"
CONTAINERFILE = ROOT / "ci" / "Containerfile"

# One plan line per curl invocation, "<outcome>:<curl_exit>"; the last line
# repeats once the plan is exhausted. Recognised outcomes:
#   200:0        success with a body
#   empty200:0   HTTP 200 carrying a zero-length body
#   302:0        a release redirect (only resolvable when --location is passed)
#   504:22/404:22 an HTTP error (--fail turns it into exit 22)
#   000:<n>      a transport failure with curl exit <n>
STUB_CURL = r"""#!/usr/bin/env bash
set -u
count=$(( $(cat "${STUB_CURL_COUNT}") + 1 ))
printf '%s' "${count}" > "${STUB_CURL_COUNT}"
printf '%s\n' "$*" >> "${STUB_CURL_ARGS}"

outcome=$(sed -n "${count}p" "${STUB_CURL_PLAN}")
if [ -z "${outcome}" ]; then
    outcome=$(tail -n 1 "${STUB_CURL_PLAN}")
fi
http_code="${outcome%%:*}"
exit_code="${outcome##*:}"

dest=""
prev=""
has_output=0
has_writeout=0
has_location=0
has_fail=0
has_showerror=0
for arg in "$@"; do
    case "${arg}" in
        --output)     has_output=1 ;;
        --write-out)  has_writeout=1 ;;
        --location)   has_location=1 ;;
        --fail)       has_fail=1 ;;
        --show-error) has_showerror=1 ;;
    esac
    if [ "${prev}" = "--output" ]; then
        dest="${arg}"
    fi
    prev="${arg}"
done
if [ "${has_output}" -eq 0 ]; then
    dest=""
fi
url="${!#}"

emit() {
    if [ "${has_writeout}" -eq 1 ]; then
        printf '%s' "$1"
    fi
    return 0
}

write_dest() {
    if [ -n "${dest}" ]; then
        printf '%s' "$1" > "${dest}"
    fi
    return 0
}

if [ "${http_code}" = "302" ]; then
    # Without --location curl stops at the redirect: exit 0, no body saved.
    if [ "${has_location}" -eq 1 ]; then
        write_dest 'stub-payload'
        emit 200
        exit 0
    fi
    emit 302
    exit 0
fi

if [ "${http_code}" = "empty200" ]; then
    write_dest ''
    emit 200
    exit 0
fi

if [ "${exit_code}" = "0" ]; then
    write_dest 'stub-payload'
    emit "${http_code}"
    exit 0
fi

if [ "${exit_code}" = "22" ]; then
    if [ "${has_fail}" -eq 1 ]; then
        # Real curl --fail writes no output file for an HTTP error response.
        emit "${http_code}"
        if [ "${has_showerror}" -eq 1 ]; then
            printf 'curl: (22) The requested URL returned error: %s\n' "${http_code}" >&2
        fi
        exit 22
    fi
    # Without --fail curl reports success and saves the error page.
    write_dest 'error-page'
    emit "${http_code}"
    exit 0
fi

# Transport failures: a short read or timeout can leave partial bytes on disk.
case "${exit_code}" in
    18|28|56) write_dest 'partial-bytes' ;;
esac
emit "${http_code}"
if [ "${has_showerror}" -eq 1 ]; then
    # Real curl names the host it could not reach; so must the stub, or the
    # "no host in the log" tests would pass vacuously.
    printf 'curl: (%s) stub transport failure for %s\n' "${exit_code}" "${url}" >&2
fi
exit "${exit_code}"
"""


class Harness:
    """A stubbed `curl` on PATH plus a runner for the downloader under test."""

    def __init__(self, tmp_path, plan):
        """Install the stub curl under tmp_path and script its outcomes.

        `plan` is the list of per-invocation outcome tokens documented on
        STUB_CURL; the last entry repeats once the plan runs out.
        """
        self.bin_dir = tmp_path / "bin"
        self.bin_dir.mkdir()
        stub = self.bin_dir / "curl"
        stub.write_text(STUB_CURL)
        stub.chmod(0o755)

        self.plan_file = tmp_path / "plan"
        self.plan_file.write_text("\n".join(plan) + "\n")
        self.count_file = tmp_path / "count"
        self.count_file.write_text("0")
        self.args_file = tmp_path / "args"
        self.args_file.write_text("")
        self.dest = tmp_path / "artifact.zip"

    def env(self, **overrides):
        """Build the child environment: stub curl first on PATH, no ambient knobs.

        Every inherited GAP_DOWNLOAD_* value is dropped so a developer who
        exports one while debugging a build cannot change these results.
        """
        env = {k: v for k, v in os.environ.items() if not k.startswith("GAP_DOWNLOAD_")}
        env.update(
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_CURL_PLAN": str(self.plan_file),
                "STUB_CURL_COUNT": str(self.count_file),
                "STUB_CURL_ARGS": str(self.args_file),
                # Keep the tests fast; the attempt bound itself is what is asserted.
                "GAP_DOWNLOAD_RETRY_BASE_DELAY": "0",
            }
        )
        env.update(overrides)
        return env

    def run(self, url="https://example.invalid/tool.zip", args=None, **env_overrides):
        """Run the downloader once; `args` overrides the whole argument vector."""
        argv = ["bash", str(SCRIPT)]
        argv += args if args is not None else [url, str(self.dest)]
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=self.env(**env_overrides),
            timeout=60,
        )

    @property
    def calls(self):
        """How many times the downloader has invoked the stub curl."""
        return int(self.count_file.read_text())


@pytest.fixture
def harness(tmp_path):
    """Return a factory that builds a Harness for a given outcome plan."""

    def _make(plan):
        """Create the Harness; one per test, sharing that test's tmp_path."""
        return Harness(tmp_path, plan)

    return _make


def test_transient_504_is_retried_until_success(harness):
    """The observed failure mode: HTTP 504 twice, then a good response."""
    h = harness(["504:22", "504:22", "200:0"])
    result = h.run()

    assert result.returncode == 0, result.stderr
    assert h.calls == 3
    assert h.dest.read_text() == "stub-payload"
    assert "HTTP 504" in result.stderr
    assert "attempt 3/4 succeeded" in result.stderr


def test_retry_exhaustion_exits_nonzero(harness):
    """A persistent 504 must still fail the build, not be swallowed."""
    h = harness(["504:22"])
    result = h.run(GAP_DOWNLOAD_MAX_ATTEMPTS="3")

    assert result.returncode == 22
    assert h.calls == 3
    assert "giving up after 3 attempts" in result.stderr
    assert "last HTTP 504" in result.stderr


def test_permanent_404_fails_fast(harness):
    """A missing artifact is permanent: one attempt, no retries."""
    h = harness(["404:22", "200:0"])
    result = h.run()

    assert result.returncode == 22
    assert h.calls == 1
    assert "failed permanently" in result.stderr
    assert "not retrying" in result.stderr


def test_transport_level_failure_is_retried(harness):
    """curl exit 28 (timeout) is transient and retried, unlike an HTTP 4xx."""
    h = harness(["000:28", "200:0"])
    result = h.run()

    assert result.returncode == 0, result.stderr
    assert h.calls == 2
    assert "curl exit 28" in result.stderr


def test_unlisted_transport_failure_is_not_retried(harness):
    """A TLS connect failure (curl 35) points at configuration, not a flaky hop."""
    h = harness(["000:35", "200:0"])
    result = h.run()

    assert result.returncode == 35
    assert h.calls == 1
    assert "failed permanently (transport error: TLS connect error)" in result.stderr
    assert "not retrying" in result.stderr


def test_overall_time_budget_stops_retrying(harness):
    """The total deadline bounds the build even with attempts left over.

    The budget is wide enough that at least one attempt must happen, so this
    cannot pass by aborting before the loop starts.
    """
    h = harness(["504:22"])
    result = h.run(
        GAP_DOWNLOAD_MAX_ATTEMPTS="50",
        GAP_DOWNLOAD_RETRY_BASE_DELAY="2",
        GAP_DOWNLOAD_TOTAL_MAX_TIME="3",
    )

    assert result.returncode == 22
    assert 1 <= h.calls <= 4, f"expected a bounded number of attempts, got {h.calls}"
    assert "attempt 1/50 failed with a transient error" in result.stderr
    assert "giving up after 3s total" in result.stderr
    assert "last HTTP 504" in result.stderr
    assert not h.dest.exists()


def test_empty_body_is_retried_then_succeeds(harness):
    """A 200 that delivers no bytes must not be installed as a tool binary."""
    h = harness(["empty200:0", "200:0"])
    result = h.run()

    assert result.returncode == 0, result.stderr
    assert h.calls == 2
    assert "empty body" in result.stderr
    assert h.dest.read_text() == "stub-payload"


def test_empty_body_exhaustion_exits_nonzero(harness):
    """Repeated empty bodies fail the build rather than leaving a 0-byte file."""
    h = harness(["empty200:0"])
    result = h.run(GAP_DOWNLOAD_MAX_ATTEMPTS="2")

    assert result.returncode != 0
    assert h.calls == 2
    assert not h.dest.exists()


def test_release_redirect_is_followed(harness):
    """Three of the four tool URLs are GitHub release redirects."""
    h = harness(["302:0"])
    result = h.run()

    assert result.returncode == 0, result.stderr
    assert h.dest.read_text() == "stub-payload"


def test_partial_output_is_removed_on_failure(harness):
    """A short read leaves bytes on disk; no later step may consume them."""
    h = harness(["000:18"])
    result = h.run(GAP_DOWNLOAD_MAX_ATTEMPTS="2")

    assert result.returncode == 18
    assert not h.dest.exists()


# Assembled at runtime rather than written as a literal, so no credential-shaped
# URL is stored in the repository for secret scanners to flag. All parts are
# synthetic and the host is reserved by RFC 2606.
SECRET_URL_PARTS = {
    "user": "ci",
    "password": "s3" + "cr3t",
    "internal_host": "artifacts.internal.corp.example",
    "path_token": "tok" + "_abcdef123456",
    "query_key": "X-Amz-Signature",
    "query_value": "dead" + "beefcafe",
}


def _secret_bearing_url():
    """Build a synthetic URL carrying credentials in userinfo, path and query."""
    p = SECRET_URL_PARTS
    return (
        f"https://{p['user']}:{p['password']}@{p['internal_host']}"
        f"/repo/{p['path_token']}/tool.zip?{p['query_key']}={p['query_value']}"
    )


def test_no_url_component_reaches_diagnostics(harness):
    """Host, path, userinfo and query must never appear in the build log.

    ci/Containerfile builds two of the four URLs from overridable ARGs, so the
    host can be an internal mirror and a path segment can be a token.
    """
    h = harness(["504:22"])
    result = h.run(url=_secret_bearing_url(), GAP_DOWNLOAD_MAX_ATTEMPTS="2")

    assert result.returncode == 22
    combined = result.stdout + result.stderr
    for label, value in SECRET_URL_PARTS.items():
        assert value not in combined, f"{label} leaked into diagnostics: {combined}"
    assert "https://" not in combined
    # The destination is the artifact identifier, and the status still shows.
    assert str(h.dest) in result.stderr
    assert "HTTP 504" in result.stderr
    # curl must not be asked for the resolved (signed) redirect target either.
    assert "url_effective" not in SCRIPT.read_text()


def test_curl_stderr_cannot_leak_the_host(harness):
    """--show-error would print 'Could not resolve host: <internal>'; it is off.

    The host-free reason text has to carry the diagnosis instead.
    """
    h = harness(["000:6"])
    result = h.run(url=_secret_bearing_url(), GAP_DOWNLOAD_MAX_ATTEMPTS="1")

    assert result.returncode == 6
    combined = result.stdout + result.stderr
    assert SECRET_URL_PARTS["internal_host"] not in combined
    assert "stub transport failure" not in combined, "curl stderr reached the log"
    assert "could not resolve host" in result.stderr
    assert "curl exit 6" in result.stderr
    code_lines = [
        line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")
    ]
    assert not any("--show-error" in line for line in code_lines)
    # The downloader must not ask curl for the resolved (signed) redirect target.
    assert "url_effective" not in SCRIPT.read_text()


def test_stdout_is_clean_on_success(harness):
    """All diagnostics go to stderr so callers can capture stdout safely."""
    h = harness(["200:0"])
    result = h.run()

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_failure_propagates_through_a_pipeline(harness):
    """`set -o pipefail` callers must still see the non-zero status."""
    h = harness(["404:22"])
    piped = subprocess.run(
        [
            "bash",
            "-c",
            f'set -euo pipefail; bash "{SCRIPT}" https://example.invalid/tool.zip "{h.dest}" | cat',
        ],
        capture_output=True,
        text=True,
        env=h.env(),
        timeout=60,
    )

    assert piped.returncode == 22
    assert piped.stdout == ""


def test_bounds_and_required_flags_are_passed_to_curl(harness):
    """Every attempt is time-bounded and uses the flags the logic depends on."""
    h = harness(["200:0"])
    result = h.run()

    assert result.returncode == 0, result.stderr
    args = h.args_file.read_text()
    for flag in (
        "--max-time 300",
        "--connect-timeout 20",
        "--fail",
        "--location",
        "--output",
        "--write-out %{http_code}",
    ):
        assert flag in args, f"missing {flag} in curl invocation: {args}"


def test_usage_error_exits_two(harness):
    h = harness(["200:0"])
    result = h.run(args=["https://example.invalid/tool.zip"])

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert h.calls == 0


@pytest.mark.parametrize(
    "knob",
    [
        "GAP_DOWNLOAD_MAX_ATTEMPTS",
        "GAP_DOWNLOAD_RETRY_BASE_DELAY",
        "GAP_DOWNLOAD_TOTAL_MAX_TIME",
    ],
)
def test_non_integer_override_is_rejected(harness, tmp_path, knob):
    """No override may reach $(( )), where bash would evaluate it as code."""
    marker = tmp_path / "pwned-marker"
    h = harness(["200:0"])
    result = h.run(**{knob: f"attempt[$(touch {marker})]"})

    assert result.returncode == 2, result.stderr
    assert knob in result.stderr
    assert h.calls == 0
    assert not marker.exists()


def test_script_is_executable():
    """ci/Containerfile COPYs the file and relies on its source mode."""
    assert os.access(SCRIPT, os.X_OK)


def test_containerfile_tool_downloads_use_the_retrying_downloader():
    """Guard the consumer path: the build root must not regress to bare curl."""
    content = CONTAINERFILE.read_text()

    assert "COPY ci/lib/download-with-retry.sh /usr/local/bin/download-with-retry" in content

    # Any curl invocation that fetches or saves something, in any flag spelling.
    fetching_curl = re.compile(r"\bcurl\b[^\n]*?(https?://|-o\b|-O\b|--output|--remote-name|>)")
    offenders = [line for line in content.splitlines() if fetching_curl.search(line)]
    assert offenders == [], f"unretried curl download(s) in ci/Containerfile: {offenders}"

    for artifact in ("yq_linux_", "openshift-client-linux.tar.gz", "ocm-linux-", "rosa_linux_"):
        assert any(
            artifact in line and "download-with-retry" in line for line in content.splitlines()
        ), f"{artifact} download is not using download-with-retry"
