"""Ensure JSON report fields render in HTML templates (no partials)."""

import re

import pytest

from reporters import generate_html_report


@pytest.fixture
def render_html():
    return generate_html_report


def test_aws_sts_validation_errors_in_html(render_html):
    data = {
        "type": "AWS STS Policy Gap Analysis",
        "baseline": "4.21.0",
        "target": "4.22.0",
        "timestamp": "2026-01-01T00:00:00",
        "validation_result": "FAIL",
        "validation_checked": True,
        "validation_details": {
            "check_1_resources": {
                "status": "FAIL",
                "errors": ["Missing file operator_iam_role_policy.json"],
                "file_count": 0,
                "warnings_structured": [],
            },
            "check_2_admin_ack": {
                "status": "PASS",
                "errors": [],
                "expected_baseline": "4.21",
            },
        },
        "aws_marketplace": {"status": "PASS", "message": "ROSA Classic available", "channels": {}},
        "comparison": {"actions": {"target_only": [], "baseline_only": []}, "file_changes": []},
        "summary": {"added": 0, "removed": 0, "total_changes": 0},
    }
    html = render_html(data)
    assert "Missing file operator_iam_role_policy.json" in html
    assert "CHECK #1: Resources Validation - FAILED" in html


def test_versions_channels_validation_errors_in_html(render_html):
    data = {
        "type": "Version Channel Gap Analysis",
        "baseline": "4.21.15",
        "target": "4.22.0",
        "baseline_minor": "4.21",
        "target_minor": "4.22",
        "is_z_stream": False,
        "timestamp": "2026-01-01T00:00:00",
        "validation_result": "FAIL",
        "validation_errors": ["Target 4.22 not in any channel"],
        "channel_availability": {
            "baseline_in_stable": True,
            "baseline_version_channels": ["stable"],
            "target_version_channels": [],
            "target_highest_channel": None,
            "baseline": {"minor": "4.21", "version": "4.21.15", "channels": {}},
            "target": {"minor": "4.22", "version": "4.22.0", "channels": {}},
        },
        "marketplace": {
            "available": False,
            "hcp": {
                "baseline": {"hcp_enabled": False, "channels": []},
                "target": {"hcp_enabled": False, "channels": []},
            },
            "gcp": {
                "baseline": {"skipped": False, "gcp_marketplace_enabled": None, "channel_group": None},
                "target": {"skipped": False, "gcp_marketplace_enabled": None, "channel_group": None},
            },
            "aws": {"target_minor_versions": []},
        },
        "summary": {
            "baseline_in_stable": True,
            "target_highest_channel": None,
            "baseline_channels": ["stable"],
            "target_channels": [],
            "target_is_ga": False,
            "marketplace_available": False,
            "api_errors": ["OCM API timeout for fast channel"],
            "gcp_skipped": False,
        },
    }
    html = render_html(data)
    assert "Target 4.22 not in any channel" in html
    assert "OCM API timeout for fast channel" in html
    # No channel_query_evidence in summary (e.g. a report from an older run):
    # the diagnostics block is skipped rather than failing the render.
    assert "Channel Query Diagnostics" not in html


def _versions_channels_data_with_evidence(evidence):
    data = {
        "type": "Version Channel Gap Analysis",
        "baseline": "5.0.1",
        "target": "5.0.2",
        "baseline_minor": "5.0",
        "target_minor": "5.0",
        "is_z_stream": True,
        "timestamp": "2026-01-01T00:00:00",
        "validation_result": "FAIL",
        "validation_errors": ["Target 5.0.2 not found in any 5.0 channel"],
        "channel_availability": {
            "baseline_in_stable": False,
            "baseline_version_channels": [],
            "target_version_channels": [],
            "target_highest_channel": "none",
            "baseline": {"minor": "5.0", "version": "5.0.1", "channels": {}},
            "target": {"minor": "5.0", "version": "5.0.2", "channels": {}},
            "query_evidence_summary": evidence,
        },
        "marketplace": {
            "available": False,
            "hcp": {
                "baseline": {"hcp_enabled": False, "channels": []},
                "target": {"hcp_enabled": True, "channels": ["candidate"]},
            },
            "gcp": {
                "baseline": {"skipped": True, "gcp_marketplace_enabled": None, "channel_group": None},
                "target": {"skipped": True, "gcp_marketplace_enabled": None, "channel_group": None},
            },
            "aws": {"target_minor_versions": []},
        },
        "summary": {
            "baseline_in_stable": False,
            "target_highest_channel": "none",
            "baseline_channels": [],
            "target_channels": [],
            "target_is_ga": True,
            "marketplace_available": False,
            "api_errors": [],
            "gcp_skipped": True,
            "channel_query_evidence": evidence,
        },
    }
    return data


# Every counter gets a distinct value so a transposed column is caught.
DISTINCT_EVIDENCE = {
    "queries": 17,
    "ok_nonempty": 11,
    "ok_empty_upstream": 12,
    "ok_all_filtered": 13,
    "errors": 14,
    "fallback_used": 15,
    "sources": {"ocm": 16, "rosa": 18, "none": 19},
}
# Header label -> the counter that column must render.
EXPECTED_CELLS = [
    ("Queries", "17"),
    ("With versions", "11"),
    ("Upstream empty", "12"),
    ("Filtered locally", "13"),
    ("Failed", "14"),
    ("ROSA fallback used", "15"),
    ("Answered by OCM / ROSA", "16 / 18"),
]


def _assert_diagnostics_columns(html):
    """Pin each diagnostics column to its counter, in order."""
    table = html.split("Channel Query Diagnostics", 1)[1].split("</table>", 1)[0]
    headers, row = table.split("</thead>", 1)
    for label, _value in EXPECTED_CELLS:
        assert label in headers, label
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    assert [c.strip() for c in cells] == [value for _label, value in EXPECTED_CELLS]


def test_versions_channels_query_evidence_in_html(render_html):
    """The diagnostics counters must reach the HTML in the documented columns."""
    html = render_html(_versions_channels_data_with_evidence(DISTINCT_EVIDENCE))
    assert "Channel Query Diagnostics" in html
    _assert_diagnostics_columns(html)


def test_versions_channels_query_evidence_partial_renders(render_html):
    """A partially populated summary must not break the whole report render."""
    html = render_html(_versions_channels_data_with_evidence({"queries": 3}))
    assert "Channel Query Diagnostics" in html


def _combined_data(versions_channels):
    return {
        "type": "Full Gap Analysis",
        "baseline": "5.0.1",
        "target": "5.0.2",
        "baseline_minor": "5.0",
        "target_minor": "5.0",
        "timestamp": "2026-01-01T00:00:00",
        "versions_channels": versions_channels,
    }


def test_combined_report_shows_query_evidence(render_html):
    """gap-all.sh sets GAP_FULL_REPORT=1, so the combined report is the only HTML."""
    html = render_html(_combined_data(_versions_channels_data_with_evidence(DISTINCT_EVIDENCE)))
    assert "Channel Query Diagnostics" in html
    _assert_diagnostics_columns(html)


def test_combined_report_query_evidence_partial_renders(render_html):
    """A partially populated summary must not abort the whole combined report."""
    data = _versions_channels_data_with_evidence({"queries": 3})
    html = render_html(_combined_data(data))
    assert "Channel Query Diagnostics" in html
    assert "CHECK #6" in html


def test_combined_report_without_query_evidence_renders(render_html):
    """The degraded status-check-only stub carries no evidence; render must not break."""
    stub = {
        "validation_result": "FAIL",
        "baseline": "5.0.1",
        "target": "5.0.2",
        "baseline_minor": "5.0",
        "target_minor": "5.0",
        "validation_errors": ["Versions & Channels script execution failed"],
        "summary": {
            "baseline_channels": [],
            "target_channels": [],
            "target_highest_channel": None,
            "target_is_ga": False,
            "marketplace_available": False,
            "api_errors": [],
            "gcp_skipped": False,
        },
        "channel_availability": {
            "baseline_in_stable": False,
            "baseline_version_channels": [],
            "target_version_channels": [],
            "baseline": {"minor": "5.0", "version": "5.0.1", "channels": {}},
            "target": {"minor": "5.0", "version": "5.0.2", "channels": {}},
        },
    }
    html = render_html(_combined_data(stub))
    assert "CHECK #6" in html
    assert "Channel Query Diagnostics" not in html


def test_ocm_version_gate_change_lists_in_html(render_html):
    data = {
        "type": "OCM Version Gate Gap Analysis",
        "baseline": "4.21.0",
        "target": "4.22.0",
        "baseline_minor": "4.21",
        "target_minor": "4.22",
        "validation_result": "FAIL",
        "is_mock_data": False,
        "gates_count": {"baseline": 1, "target": 1},
        "baseline_gates": [],
        "target_gates": [],
        "comparison": {
            "common_gates_count": 0,
            "new_gates_count": 1,
            "deprecated_gates_count": 1,
            "common_gates": [],
            "new_gates": [{"label": "api.openshift.com/new-gate", "description": "New gate"}],
            "deprecated_gates": [{"label": "api.openshift.com/old-gate", "description": "Old gate"}],
        },
        "skipped_labels": ["api.openshift.com/wif"],
        "configuration_validation": {"valid": False, "errors": ["Gate metadata mismatch"]},
    }
    html = render_html(data)
    assert "api.openshift.com/new-gate" in html
    assert "api.openshift.com/old-gate" in html
