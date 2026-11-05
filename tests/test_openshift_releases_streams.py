"""Regression tests for major-aware stable stream resolution (Python resolver).

Guards the failure seen in periodic-ci-openshift-online-rosa-gap-analysis-main-
periodics-nightly-5-0: with GA=5.0 the resolver took the z-stream path and looked
for 5.0.x in the hardcoded "4-stable" stream, so it reported
"No stable versions found for 5.0.x" even though 5-stable held 5.0.1 and 5.0.0.

All tests run offline against fixtures; no API is contacted.
"""

import pytest

import openshift_releases

from tests.fixtures.accepted_streams import (
    ACCEPTED_STREAMS,
    ACCEPTED_STREAMS_AT_GA,
    ACCEPTED_STREAMS_EMPTY_5,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a resolver under test tries to reach the network."""
    def _blocked(*_args, **_kwargs):
        raise AssertionError("test attempted a network call")

    monkeypatch.setattr(openshift_releases, "urlopen", _blocked)


def _use_streams(monkeypatch, streams):
    monkeypatch.setattr(openshift_releases, "fetch_accepted_streams", lambda: streams)


# --- stream selection -------------------------------------------------------

@pytest.mark.parametrize("version,expected", [
    ("4.21", "4-stable"),
    ("4.22.21", "4-stable"),
    ("5.0", "5-stable"),
    ("5.0.1", "5-stable"),
    ("5.1.0-ec.1", "5-stable"),
])
def test_stable_stream_follows_major(version, expected):
    assert openshift_releases.stable_stream_for_version(version) == expected


@pytest.mark.parametrize("version,expected", [
    ("4.23", "4-dev-preview"),
    ("5.1", "5-dev-preview"),
])
def test_dev_preview_stream_follows_major(version, expected):
    assert openshift_releases.dev_preview_stream_for_version(version) == expected


# --- get_previous_z_stream_version -----------------------------------------

def test_previous_z_stream_resolves_5x_from_5_stable(monkeypatch):
    """Regression: 5.0 previously failed because only 4-stable was searched."""
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    assert openshift_releases.get_previous_z_stream_version("5.0") == "5.0.0"


def test_previous_z_stream_preserves_4x_behavior(monkeypatch):
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    assert openshift_releases.get_previous_z_stream_version("4.22") == "4.22.20"
    assert openshift_releases.get_previous_z_stream_version("4.21") == "4.21.29"


def test_previous_z_stream_ignores_rc_builds_at_ga(monkeypatch):
    """At 5.0 GA the only z-stream is 5.0.0; the 5.0.0-rc.* builds are not one."""
    _use_streams(monkeypatch, ACCEPTED_STREAMS_AT_GA)
    assert openshift_releases.get_previous_z_stream_version("5.0") is None


def test_previous_z_stream_errors_when_stream_missing(monkeypatch, capsys):
    """A genuinely absent stream must still be a hard error, with diagnostics."""
    _use_streams(monkeypatch, ACCEPTED_STREAMS_EMPTY_5)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_previous_z_stream_version("6.0")
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "No stable versions found for 6.0.x" in err
    assert "6-stable" in err
    assert "is not present" in err
    assert "4-stable" in err  # lists the streams that do exist


def test_previous_z_stream_errors_when_line_absent_from_existing_stream(monkeypatch, capsys):
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_previous_z_stream_version("5.4")
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "No stable versions found for 5.4.x" in err
    assert "5-stable holds 4 accepted version(s)" in err
    assert "5.0.1" in err


# --- get_latest_stable_version ---------------------------------------------

def test_latest_stable_resolves_5x_from_5_stable(monkeypatch):
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    assert openshift_releases.get_latest_stable_version(ga_version="5.0") == "5.0.1"


def test_latest_stable_preserves_4x_behavior(monkeypatch):
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    assert openshift_releases.get_latest_stable_version(ga_version="4.21") == "4.21.30"
    assert openshift_releases.get_latest_stable_version(ga_version="4.22") == "4.22.21"


def test_latest_stable_excludes_rc_builds(monkeypatch):
    _use_streams(monkeypatch, ACCEPTED_STREAMS_AT_GA)
    assert openshift_releases.get_latest_stable_version(ga_version="5.0") == "5.0.0"


def test_latest_stable_errors_on_empty_stream(monkeypatch, capsys):
    _use_streams(monkeypatch, ACCEPTED_STREAMS_EMPTY_5)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_latest_stable_version(ga_version="5.0")
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "No versions found in 5-stable accepted stream" in err
    assert "5-stable holds 0 accepted version(s)" in err


# --- resolve_openshift_version ---------------------------------------------

def _stub_resolution(monkeypatch, streams, ga_version):
    _use_streams(monkeypatch, streams)
    monkeypatch.setattr(openshift_releases, "get_latest_ga_version", lambda: ga_version)


def test_resolve_version_5_0_after_ga(monkeypatch):
    """End-to-end parity with the shell path used by gap-all.sh."""
    _stub_resolution(monkeypatch, ACCEPTED_STREAMS, "5.0")
    assert openshift_releases.resolve_openshift_version("5.0") == ("5.0.0", "5.0.1")


def test_resolve_version_4x_z_stream_unchanged(monkeypatch):
    _stub_resolution(monkeypatch, ACCEPTED_STREAMS, "4.22")
    assert openshift_releases.resolve_openshift_version("4.22") == ("4.22.20", "4.22.21")


def test_resolve_version_4x_pre_ga_cross_minor_unchanged(monkeypatch):
    _stub_resolution(monkeypatch, ACCEPTED_STREAMS, "4.22")
    assert openshift_releases.resolve_openshift_version("4.23") == ("4.22.21", "4.23.0-ec.2")


def test_resolve_version_skips_when_single_z_stream(monkeypatch):
    _stub_resolution(monkeypatch, ACCEPTED_STREAMS_AT_GA, "5.0")
    assert openshift_releases.resolve_openshift_version("5.0") == (None, None)


def test_resolve_version_skips_freshly_ga_4x_line(monkeypatch):
    """A 4.y line whose only other 4-stable entries are its own RCs has no previous
    z-stream, so the run is skipped instead of comparing 4.22.0 against 4.22.0-rc.4."""
    streams = {"4-stable": ["4.22.0", "4.22.0-rc.4", "4.22.0-rc.3", "4.21.30"]}
    _stub_resolution(monkeypatch, streams, "4.22")
    assert openshift_releases.resolve_openshift_version("4.22") == (None, None)


def test_resolve_version_5_1_baseline_line_has_no_stable_release(monkeypatch, capsys):
    """4.23 → 5.1 spans majors, and 4.23 has not shipped a stable release yet.

    The baseline is looked up in 4-stable (not the GA major's 5-stable) and, finding
    nothing there, fails loudly with diagnostics. Mirrors the shell resolver.
    """
    _stub_resolution(monkeypatch, ACCEPTED_STREAMS, "5.0")
    with pytest.raises(SystemExit) as exc:
        openshift_releases.resolve_openshift_version("5.1")
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "No stable versions found matching GA version line 4.23.x" in err
    assert "4-stable holds 7 accepted version(s)" in err


# --- baseline / target precedence ------------------------------------------

def test_baseline_priority_prefers_stable_5x(monkeypatch):
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    assert openshift_releases.get_latest_version_baseline_priority("5.0") == "5.0.1"
    assert openshift_releases.get_latest_version_baseline_priority("4.22") == "4.22.21"


def test_target_priority_falls_back_to_dev_preview_ec(monkeypatch):
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    assert openshift_releases.get_latest_version_target_priority("5.1") == "5.1.0-ec.1"


def test_target_priority_reports_every_consulted_stream_on_failure(monkeypatch, capsys):
    _use_streams(monkeypatch, ACCEPTED_STREAMS)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_latest_version_target_priority("5.4")
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "5-stable" in err
    assert "5-dev-preview" in err
    assert "5.4.0-0.ci" in err
    assert "5.4.0-0.nightly" in err


def test_latest_candidate_reports_both_streams_on_failure(monkeypatch, capsys):
    _use_streams(monkeypatch, ACCEPTED_STREAMS_AT_GA)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_latest_candidate_version(dev_version="5.1")
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "no candidate version found for 5.1" in err.lower()
    assert "5-dev-preview is not present" in err


# --- diagnostics ------------------------------------------------------------

def test_stream_lookup_diagnostic_is_bounded(capsys):
    # Newest first, as the accepted API returns them
    streams = {"5-stable": [f"5.0.{i}" for i in range(39, -1, -1)]}
    openshift_releases.log_stream_lookup_failure("5-stable", "5.9", streams)

    err = capsys.readouterr().err
    assert "5-stable holds 40 accepted version(s)" in err
    assert "5.0.39" in err  # newest is reported
    assert "5.0.29" not in err  # capped at the 10 newest
    assert err.count("5.0.") <= openshift_releases._DIAGNOSTIC_SAMPLE_SIZE + 1


def test_stream_lookup_diagnostic_handles_unexpected_payload(capsys):
    openshift_releases.log_stream_lookup_failure("5-stable", "5.0", ["not", "a", "mapping"])
    assert "Could not parse the accepted streams response" in capsys.readouterr().err


def test_stream_lookup_diagnostic_names_public_api(capsys):
    openshift_releases.log_stream_lookup_failure("5-stable", "5.0", ACCEPTED_STREAMS)
    err = capsys.readouterr().err
    assert openshift_releases.ACCEPTED_STREAMS_API in err
    assert "amd64.ocp.releases.ci.openshift.org" in err
