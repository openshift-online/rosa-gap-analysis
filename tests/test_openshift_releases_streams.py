"""Regression tests for major-aware stable stream resolution (Python resolver).

Guards the failure seen in periodic-ci-openshift-online-rosa-gap-analysis-main-
periodics-nightly-5-0: with GA=5.0 the resolver took the z-stream path and looked
for 5.0.x in the hardcoded "4-stable" stream, so it reported
"No stable versions found for 5.0.x" even though 5-stable held 5.0.1 and 5.0.0.

All tests run offline against fixtures; no API is contacted.
"""

import json

import pytest

import openshift_releases

from tests.fixtures.accepted_streams import (
    ACCEPTED_STREAMS,
    ACCEPTED_STREAMS_AT_GA,
    ACCEPTED_STREAMS_EMPTY_5,
)
from tests.fixtures.sippy_releases import (
    MIXED_PRODUCT_LATEST_GA,
    MIXED_PRODUCT_RELEASES,
    NO_OCP_GA_RELEASES,
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


# --- get_latest_ga_version: OCP-only selection ------------------------------
#
# Sippy's ga_dates is published for every product it tracks, so the resolver
# has to pick the OCP releases out of it. Guards the failure seen in
# periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-4-19:
# logging-6.6 entered ga_dates and the whole key set was sorted as OpenShift
# versions, so resolution aborted on a release this repository never wanted.

def _use_releases(monkeypatch, payload):
    monkeypatch.setattr(openshift_releases, "fetch_sippy_releases", lambda: payload)


def test_latest_ga_ignores_other_products(monkeypatch):
    """The live mix: OCP 4.19/5.0, OCP Logging logging-6.6, OKD 5.0-okd."""
    _use_releases(monkeypatch, MIXED_PRODUCT_RELEASES)
    assert openshift_releases.get_latest_ga_version() == MIXED_PRODUCT_LATEST_GA


def test_latest_ga_selects_by_product_not_key_shape(monkeypatch):
    """A non-OCP release with a version-shaped key must still be excluded,
    which only the product metadata can decide."""
    _use_releases(monkeypatch, {
        "ga_dates": {"4.19": "2025-06-17", "9.9": "2026-01-01"},
        "release_attrs": {
            "4.19": {"product": "OCP"},
            "9.9": {"product": "OKD"},
        },
    })
    assert openshift_releases.get_latest_ga_version() == "4.19"


def test_latest_ga_orders_minors_numerically_not_lexically(monkeypatch):
    """4.9 sorts after 4.20 lexically; the numeric sort must still win."""
    _use_releases(monkeypatch, {"ga_dates": {"4.9": "d", "4.20": "d", "4.10": "d"}})
    assert openshift_releases.get_latest_ga_version() == "4.20"


def test_latest_ga_treats_a_payload_without_release_attrs_as_ocp(monkeypatch):
    """An older Sippy has no release_attrs; the numeric guard alone decides,
    exactly as before this filter existed."""
    _use_releases(monkeypatch, {"ga_dates": {"4.19": "d", "5.0": "d"}})
    assert openshift_releases.get_latest_ga_version() == "5.0"


def test_latest_ga_fails_when_no_ocp_release_has_ga(monkeypatch, capsys):
    """Fail loudly instead of handing back another product's version."""
    _use_releases(monkeypatch, NO_OCP_GA_RELEASES)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_latest_ga_version()
    assert exc.value.code == 1
    assert "No GA OCP versions found" in capsys.readouterr().err


@pytest.mark.parametrize("payload,expected", [
    # Nothing to select from.
    ({}, []),
    ({"ga_dates": {}}, []),
    ({"ga_dates": {"logging-6.6": "d"}}, []),
    # release_attrs of the wrong type falls back to the numeric guard...
    ({"ga_dates": {"4.19": "d"}, "release_attrs": "not-a-mapping"}, ["4.19"]),
    # ...and so does a single entry that is not an object.
    ({"ga_dates": {"4.19": "d"}, "release_attrs": {"4.19": "not-a-mapping"}}, ["4.19"]),
    # Only an ABSENT product is defaulted to OCP; a present one is obeyed
    # whatever its JSON type, so `false` is not read as "unset".
    ({"ga_dates": {"4.19": "d"}, "release_attrs": {"4.19": {}}}, ["4.19"]),
    ({"ga_dates": {"4.19": "d"}, "release_attrs": {"4.19": {"product": None}}}, ["4.19"]),
    ({"ga_dates": {"4.19": "d"}, "release_attrs": {"4.19": {"product": False}}}, []),
    # Degenerate keys are skipped, never fed to int().
    ({"ga_dates": {"4.19": "d", "": "d", "4.": "d", "4.x": "d"}}, ["4.19"]),
    # Non-ASCII digits are skipped too. str.isdigit() accepts them, and int()
    # accepts fullwidth ones while raising on a superscript, so without the
    # ASCII test this both diverges from jq's 48-57 check and can raise.
    ({"ga_dates": {"4.19": "d", "４.１９": "d", "4.1²": "d"}}, ["4.19"]),
    # A non-mapping ga_dates is ignored, not iterated: iterating the string
    # would offer its characters as versions and resolve "9".
    ({"ga_dates": "4.19"}, []),
    ({"ga_dates": ["4.19", "5.0"]}, []),
    ({"ga_dates": 5}, []),
])
def test_ocp_ga_versions_handles_an_unexpected_payload(payload, expected):
    """Selection must neither raise nor invent a version, whatever the payload:
    every key that reaches int() has been proved to be dotted digits first."""
    assert openshift_releases._ocp_ga_versions(payload) == expected


# --- fetch_sippy_releases / fetch_sippy_ga_dates ----------------------------

def _stub_sippy_response(monkeypatch, body):
    """Stub urlopen with a context manager returning `body` as raw bytes."""
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return body.encode()

    monkeypatch.setattr(openshift_releases, "urlopen", lambda *a, **kw: _Response())


def test_fetch_sippy_releases_returns_the_whole_payload(monkeypatch):
    _stub_sippy_response(monkeypatch, json.dumps(MIXED_PRODUCT_RELEASES))
    assert openshift_releases.fetch_sippy_releases() == MIXED_PRODUCT_RELEASES
    assert openshift_releases.fetch_sippy_ga_dates() == MIXED_PRODUCT_RELEASES["ga_dates"]


@pytest.mark.parametrize("body,message", [
    ('["4.21"]', "response root is JSON list, expected object"),
    ('"4.21"', "response root is JSON str, expected object"),
    ('{"ga_dates": ["4.21"]}', "ga_dates is JSON list, expected object"),
    ('{"ga_dates": "4.21"}', "ga_dates is JSON str, expected object"),
])
def test_fetch_sippy_ga_dates_fails_loudly_on_an_unexpected_payload(
    monkeypatch, capsys, body, message
):
    """Degrading to an empty mapping would answer "nothing is GA" in silence,
    which flips Check #6 to candidate-only and makes Checks #9-#13 look for the
    wrong Prow jobs. Mirrors the shell resolver's own classification."""
    _stub_sippy_response(monkeypatch, body)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.fetch_sippy_ga_dates()
    assert exc.value.code == 1
    assert message in capsys.readouterr().err


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
