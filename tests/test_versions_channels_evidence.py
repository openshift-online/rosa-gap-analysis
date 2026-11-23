"""CHECK #6 channel-query provenance: offline, deterministic, no CLI calls.

Every test stubs subprocess.run, so nothing here contacts OCM, ROSA or any
cloud API. The assertions cover the four cases the artifacts must distinguish —
empty upstream success, locally filtered data, ROSA fallback, and failure —
plus the rule that no raw CLI output reaches the artifact.
"""

import json
import subprocess
from unittest.mock import patch

from tests.conftest import gap_versions_channels as gvc


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ocm_payload(raw_ids):
    return json.dumps({"items": [{"raw_id": raw_id} for raw_id in raw_ids]})


def _runner(responses):
    """Return a subprocess.run stub keyed by the CLI being invoked."""

    def run(cmd, *args, **kwargs):
        result = responses[cmd[0]]
        if isinstance(result, Exception):
            raise result
        return result

    return run


def test_empty_upstream_success_is_distinguishable():
    """OCM answered successfully with zero items — not an error, not a filter drop."""
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload([]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    assert versions == []
    assert err is None
    assert evidence["source"] == "ocm"
    assert evidence["fallback_used"] is False
    assert evidence["outcome"] == gvc.OUTCOME_OK_EMPTY_UPSTREAM
    attempt = evidence["attempts"][0]
    assert attempt["status"] == "ok"
    assert attempt["upstream_item_count"] == 0
    assert attempt["matched_count"] == 0
    assert attempt["filtered_out_count"] == 0


def test_locally_filtered_data_is_distinguishable():
    """Upstream returned versions; all were dropped by the minor-version filter."""
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(["5.1.0", "4.22.3", ""]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    assert versions == []
    assert err is None
    assert evidence["outcome"] == gvc.OUTCOME_OK_ALL_FILTERED
    attempt = evidence["attempts"][0]
    assert attempt["upstream_item_count"] == 3
    assert attempt["matched_count"] == 0
    assert attempt["filtered_out_count"] == 3
    assert attempt["filtered_out_sample"] == ["5.1.0", "4.22.3"]
    assert attempt["filtered_out_unparsable_count"] == 1


def test_matched_versions_report_partial_filtering():
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(["5.0.1", "5.0.2", "5.1.0"]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "candidate")

    assert versions == ["5.0.1", "5.0.2"]
    assert err is None
    assert evidence["outcome"] == gvc.OUTCOME_OK_NONEMPTY
    attempt = evidence["attempts"][0]
    assert (attempt["upstream_item_count"], attempt["matched_count"]) == (3, 2)
    assert attempt["filtered_out_sample"] == ["5.1.0"]


def test_filtered_out_sample_is_bounded():
    raw_ids = [f"4.22.{i}" for i in range(20)]
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(raw_ids))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        _versions, _err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    attempt = evidence["attempts"][0]
    assert attempt["filtered_out_count"] == 20
    assert len(attempt["filtered_out_sample"]) == gvc.EVIDENCE_SAMPLE_LIMIT


def test_rosa_fallback_is_recorded():
    """OCM failed, ROSA answered: the artifact must name the source that won."""
    responses = {
        "ocm": FakeCompleted(returncode=1, stderr="token refresh failed"),
        "rosa": FakeCompleted(stdout="VERSION  DEFAULT\n5.0.2    yes\n4.22.1   no\n"),
    }
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "candidate")

    assert versions == ["5.0.2"]
    assert err is None
    assert evidence["source"] == "rosa"
    assert evidence["fallback_used"] is True
    assert evidence["outcome"] == gvc.OUTCOME_OK_NONEMPTY
    assert [a["source"] for a in evidence["attempts"]] == ["ocm", "rosa"]
    assert evidence["attempts"][0]["error_kind"] == "exit_code"
    assert evidence["attempts"][1]["upstream_item_count"] == 2
    assert evidence["attempts"][1]["matched_count"] == 1


def test_both_sources_failing_is_recorded_as_error():
    responses = {
        "ocm": FileNotFoundError("ocm"),
        "rosa": FakeCompleted(returncode=2, stderr="not logged in"),
    }
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    assert versions == []
    assert "rosa fallback also failed" in err
    assert evidence["source"] == "none"
    assert evidence["outcome"] == gvc.OUTCOME_ERROR
    assert [a["error_kind"] for a in evidence["attempts"]] == ["cli_not_found", "exit_code"]


def test_timeout_is_recorded_as_a_sanitized_error_kind():
    responses = {
        "ocm": subprocess.TimeoutExpired(cmd=["ocm"], timeout=30),
        "rosa": subprocess.TimeoutExpired(cmd=["rosa"], timeout=30),
    }
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        _versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    assert "timeout" in err
    assert [a["error_kind"] for a in evidence["attempts"]] == ["timeout", "timeout"]
    assert evidence["outcome"] == gvc.OUTCOME_ERROR


def test_malformed_json_is_recorded_as_invalid_json():
    responses = {
        "ocm": FakeCompleted(stdout="<html>502 Bad Gateway</html>"),
        "rosa": FakeCompleted(returncode=1, stderr="unavailable"),
    }
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        _versions, _err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    assert evidence["attempts"][0]["error_kind"] == "invalid_json"
    assert evidence["fallback_used"] is True
    assert "html" not in json.dumps(evidence)


def test_invalid_channel_group_is_recorded_without_querying():
    with patch.object(gvc.subprocess, "run", side_effect=AssertionError("must not run")):
        versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "Stable; rm -rf /")

    assert versions == []
    assert "Invalid channel group format" in err
    assert evidence["attempts"][0]["source"] == "input"
    assert evidence["attempts"][0]["error_kind"] == "invalid_channel_group"
    assert "rm -rf" not in json.dumps(evidence)


def test_filtered_out_sample_is_deduplicated():
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(["4.22.1"] * 4 + ["4.22.2"]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        _versions, _err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    attempt = evidence["attempts"][0]
    assert attempt["filtered_out_count"] == 5
    assert attempt["filtered_out_sample"] == ["4.22.1", "4.22.2"]


def test_invalid_input_is_recorded_without_querying():
    with patch.object(gvc.subprocess, "run", side_effect=AssertionError("must not run")):
        versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0.1", "stable")

    assert versions == []
    assert "Invalid minor version format" in err
    assert evidence["outcome"] == gvc.OUTCOME_ERROR
    assert evidence["attempts"][0]["error_kind"] == "invalid_minor_version"


def test_evidence_excludes_raw_cli_output_and_secrets():
    """Only allowlisted fields are retained; stderr/stdout never reach the evidence."""
    secret_stderr = "Bearer sk-live-SUPERSECRET on https://user:pw@sso.example/token"
    responses = {
        "ocm": FakeCompleted(returncode=1, stderr=secret_stderr),
        "rosa": FakeCompleted(returncode=1, stderr=secret_stderr),
    }
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        _versions, err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    serialized = json.dumps(evidence)
    for marker in ("sk-live-SUPERSECRET", "Bearer", "user:pw", "sso.example"):
        assert marker not in serialized
    allowed_attempt_keys = {
        "source", "query", "status", "error_kind", "upstream_item_count",
        "matched_count", "filtered_out_count", "filtered_out_sample",
        "filtered_out_unparsable_count",
    }
    for attempt in evidence["attempts"]:
        assert set(attempt) == allowed_attempt_keys
        assert set(attempt["query"]) <= {
            "command", "endpoint", "search", "size", "order", "local_filter",
            "channel_group", "check",
        }
    # The pre-existing api_errors channel still carries the CLI message verbatim;
    # that behaviour is unchanged and separate from the sanitized evidence.
    assert secret_stderr in err


def test_unparsable_tokens_are_counted_not_echoed():
    raw_ids = ["5.1.0", "<html>503 Service Unavailable</html>", "not-a-version"]
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(raw_ids))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        _versions, _err, evidence = gvc.fetch_ocm_channel_data_with_evidence("5.0", "stable")

    attempt = evidence["attempts"][0]
    assert attempt["filtered_out_sample"] == ["5.1.0"]
    assert attempt["filtered_out_unparsable_count"] == 2
    assert "html" not in json.dumps(evidence)


def test_legacy_two_tuple_caller_contract_is_preserved():
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(["5.0.1"]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        result = gvc.fetch_ocm_channel_data("5.0", "stable")

    assert result == (["5.0.1"], None)


def test_analyze_channel_availability_keeps_results_and_adds_evidence():
    """Evidence is additive: channel verdicts and api_errors are unchanged."""
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(["5.0.1", "5.1.0"]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        analysis = gvc.analyze_channel_availability(
            "5.0", "5.0", "5.0.1", "5.0.1",
            baseline_channels=["stable"], target_channels=["candidate"],
        )

    assert analysis["api_errors"] == []
    assert analysis["baseline_version_channels"] == ["stable"]
    assert analysis["target_version_channels"] == ["candidate"]
    assert analysis["baseline_in_stable"] is True
    assert analysis["target_highest_channel"] == "candidate"
    assert analysis["baseline"]["channels"]["stable"]["versions"] == ["5.0.1"]

    summary = analysis["query_evidence_summary"]
    assert summary["queries"] == 2
    assert summary[gvc.OUTCOME_OK_NONEMPTY] == 2
    assert summary["sources"] == {"ocm": 2, "rosa": 0, "none": 0}
    assert summary["fallback_used"] == 0


def test_evidence_summary_separates_empty_upstream_from_filtering():
    """The CI symptom: every channel empty — with the cause now recorded."""
    responses = {"ocm": FakeCompleted(stdout=_ocm_payload(["4.22.1"]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        filtered = gvc.analyze_channel_availability(
            "5.0", "5.0", "5.0.1", "5.0.2",
            baseline_channels=["stable"], target_channels=["stable"],
        )

    responses = {"ocm": FakeCompleted(stdout=_ocm_payload([]))}
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        empty = gvc.analyze_channel_availability(
            "5.0", "5.0", "5.0.1", "5.0.2",
            baseline_channels=["stable"], target_channels=["stable"],
        )

    assert filtered["target_version_channels"] == empty["target_version_channels"] == []
    assert filtered["query_evidence_summary"][gvc.OUTCOME_OK_ALL_FILTERED] == 2
    assert filtered["query_evidence_summary"][gvc.OUTCOME_OK_EMPTY_UPSTREAM] == 0
    assert empty["query_evidence_summary"][gvc.OUTCOME_OK_EMPTY_UPSTREAM] == 2
    assert empty["query_evidence_summary"][gvc.OUTCOME_OK_ALL_FILTERED] == 0


def test_recorded_query_strings_are_length_capped():
    """No evidence field may grow unbounded, including the recorded query shape."""
    attempt = gvc._new_attempt('ocm', {'search': 'x' * 500, 'size': 200})
    assert len(attempt['query']['search']) == gvc.EVIDENCE_TEXT_LIMIT + 1
    assert attempt['query']['search'].endswith('…')
    assert attempt['query']['size'] == 200


def test_summary_invariant_holds_for_unknown_outcome_and_source():
    """ok_* + errors == queries == sum(sources), whatever an attempt reports."""
    analysis = {
        'baseline': {'channels': {
            'stable': {'query_evidence': {'outcome': 'something_new', 'source': 'curl'}},
        }},
        'target': {'channels': {
            'stable': {'query_evidence': {'outcome': gvc.OUTCOME_OK_NONEMPTY, 'source': 'ocm'}},
            # Truthy but missing both keys: must still be counted once, as an error.
            'candidate': {'query_evidence': {'attempts': []}},
        }},
    }
    summary = gvc.summarize_channel_query_evidence(analysis)
    outcomes = (summary[gvc.OUTCOME_OK_NONEMPTY] + summary[gvc.OUTCOME_OK_EMPTY_UPSTREAM]
                + summary[gvc.OUTCOME_OK_ALL_FILTERED] + summary['errors'])
    assert summary['queries'] == 3
    assert outcomes == summary['queries']
    assert sum(summary['sources'].values()) == summary['queries']
    assert summary['sources']['none'] == 2


def test_evidence_summary_counts_errors_and_fallback():
    responses = {
        "ocm": FakeCompleted(returncode=1, stderr="boom"),
        "rosa": FakeCompleted(returncode=1, stderr="boom"),
    }
    with patch.object(gvc.subprocess, "run", side_effect=_runner(responses)):
        analysis = gvc.analyze_channel_availability(
            "5.0", "5.0", "5.0.1", "5.0.2",
            baseline_channels=["stable"], target_channels=["stable"],
        )

    summary = analysis["query_evidence_summary"]
    assert summary["errors"] == 2
    assert summary["fallback_used"] == 2
    assert summary["sources"] == {"ocm": 0, "rosa": 0, "none": 2}
    assert len(analysis["api_errors"]) == 2
