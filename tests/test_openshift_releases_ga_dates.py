"""Regression tests for GA-version resolution from Sippy's ga_dates (Python resolver).

Guards the failure seen in periodic-ci-openshift-online-rosa-gap-analysis-main-
periodics-nightly-4-20: Sippy keys `ga_dates` by release line and not every line
is OpenShift — the live payload carries `logging-6.6` beside 3.11/4.x/5.x — so
converting every key to a number resolved no GA version at all even though 19
usable minors were in the response.

The shell copy of the resolver (the one gap-all.sh runs) is covered by the
matching cases in tests/test_openshift_releases_sh.py.

All tests run offline against fixtures; no API is contacted.
"""

import pytest

import openshift_releases

from tests.fixtures.ga_dates import (
    LIVE_GA_DATES,
    LIVE_GA_DATES_LATEST,
    NON_VERSION_KEYS,
    NO_OPENSHIFT_GA_DATES,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if the resolver under test tries to reach the network."""
    def _blocked(*_args, **_kwargs):
        raise AssertionError("test attempted a network call")

    monkeypatch.setattr(openshift_releases, "urlopen", _blocked)


def _use_ga_dates(monkeypatch, ga_dates):
    monkeypatch.setattr(openshift_releases, "fetch_sippy_ga_dates", lambda: ga_dates)


def test_latest_ga_version_ignores_non_openshift_release_lines(monkeypatch):
    """The live payload, verbatim: `logging-6.6` must be ignored, not fatal."""
    _use_ga_dates(monkeypatch, LIVE_GA_DATES)
    assert openshift_releases.get_latest_ga_version() == LIVE_GA_DATES_LATEST


def test_latest_ga_version_orders_minors_numerically(monkeypatch):
    """4.9 sorts after 4.20 lexically; the numeric sort must still win, and a
    foreign key alongside must not disturb it."""
    _use_ga_dates(monkeypatch, {"4.9": "d", "4.20": "d", "4.10": "d", "logging-6.6": "d"})
    assert openshift_releases.get_latest_ga_version() == "4.20"


def test_latest_ga_version_errors_when_no_key_is_a_version(monkeypatch, capsys):
    """Fail-closed is preserved: with nothing version-shaped left there is no
    GA version to return, so the resolver must exit rather than invent one."""
    _use_ga_dates(monkeypatch, NO_OPENSHIFT_GA_DATES)
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_latest_ga_version()
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "No OpenShift major.minor GA versions found in Sippy API" in err
    assert "2 ga_dates key(s)" in err
    # Counts only: response content must not reach a CI artifact.
    for key in NO_OPENSHIFT_GA_DATES:
        assert key not in err


def test_latest_ga_version_errors_on_empty_ga_dates(monkeypatch, capsys):
    """The pre-existing empty-payload branch is unchanged."""
    _use_ga_dates(monkeypatch, {})
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_latest_ga_version()
    assert exc.value.code == 1
    assert "No GA versions found in Sippy API" in capsys.readouterr().err


@pytest.mark.parametrize("key", NON_VERSION_KEYS)
def test_latest_ga_version_rejects_keys_that_are_not_major_minor(monkeypatch, key):
    """Only bare numeric major.minor counts; anything else is ignored, so a
    payload holding just that key resolves nothing."""
    _use_ga_dates(monkeypatch, {key: "d"})
    with pytest.raises(SystemExit) as exc:
        openshift_releases.get_latest_ga_version()
    assert exc.value.code == 1


def test_latest_ga_version_is_never_a_key_with_trailing_whitespace(monkeypatch):
    """A near-miss key must not win over a real one either: `$`-anchored, this
    returned the literal "4.21\\n", which then flows into BASE_VERSION."""
    _use_ga_dates(monkeypatch, {"4.20": "d", "4.21\n": "d"})
    assert openshift_releases.get_latest_ga_version() == "4.20"


def test_is_ga_minor_version_is_deliberately_unfiltered():
    """Membership is a plain lookup and the filter must not leak into it: it
    answers "is this minor GA", so a caller asking about a line Sippy lists --
    including `logging-6.6` -- still gets Sippy's answer, and an unlisted minor
    is still pre-GA."""
    assert openshift_releases.is_ga_minor_version("4.22", ga_dates=LIVE_GA_DATES)
    assert openshift_releases.is_ga_minor_version("logging-6.6", ga_dates=LIVE_GA_DATES)
    assert not openshift_releases.is_ga_minor_version("5.1", ga_dates=LIVE_GA_DATES)
