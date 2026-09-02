#!/usr/bin/env python3
"""Target E2E Validation and alert monitoring - consume target-version rosa-e2e JUnit."""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from common import log_error, log_info, log_success, log_warning
from openshift_releases import extract_minor_version, resolve_gap_versions
from prow_artifacts import (
    DEFAULT_TOPOLOGIES,
    TOPOLOGY_CHOICES,
    TOPOLOGY_HELP,
    find_e2e_junit,
    load_e2e_junit_from_path,
    osd_gcp_skip_reason,
    topology_coverage_summary,
    topology_display_name,
)
from reporters import generate_html_report, generate_json_report, generate_status_report

CHECK_NUMBER = 12
CHECK_NAME = "Target E2E Validation and alert monitoring"
REPORT_SLUG = "e2e-validation"
ALERT_NOT_PRESENT_REASON = (
    "alert monitoring test not present in JUnit "
    "(VerifyNoCriticalAlerts is not in rosa-e2e yet)"
)
# Match Ginkgo It() names once the rosa-e2e verifier lands (September).
ALERT_MARKERS = (
    "should not have unexpected critical alerts firing",
    "verifynocriticalalerts",
    "no unexpected critical alerts",
)
NOTE = (
    "Informational check. Target-version only: consumes junit-rosa-e2e.xml from "
    "the existing rosa-e2e test step (as: rosa-e2e-test). Does not compare "
    "baseline vs target. Missing JUnit is SKIP. Failed e2e tests are reported "
    "as FAIL in the report (current e2e quality) but do not fail this job. "
    "OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). "
    "Alert monitoring looks for a future VerifyNoCriticalAlerts-style test; "
    "until that test exists the subsection is SKIP and does not fail the check. "
    "Check #10 alerts.json is definitions only and is not used here."
)


def _local_tag(tag):
    return tag.rsplit("}", 1)[-1] if tag else ""


def _child(element, name):
    for child in list(element):
        if _local_tag(child.tag) == name:
            return child
    return None


def is_alert_test(name):
    lowered = (name or "").lower()
    return any(marker in lowered for marker in ALERT_MARKERS)


def parse_junit(xml_text):
    """Parse Ginkgo/JUnit XML into cases and suite totals."""
    root = ET.fromstring(xml_text)
    tag = _local_tag(root.tag)
    if tag == "testsuites":
        suites = [child for child in list(root) if _local_tag(child.tag) == "testsuite"]
        if not suites:
            suites = [root]
    elif tag == "testsuite":
        suites = [root]
    else:
        raise ValueError(f"unexpected JUnit root element: {root.tag}")

    cases = []
    tests = failures = errors = skipped = 0
    for suite in suites:
        tests += int(suite.get("tests") or 0)
        failures += int(suite.get("failures") or 0)
        errors += int(suite.get("errors") or 0)
        skipped += int(suite.get("skipped") or suite.get("disabled") or 0)
        for case in suite.iter():
            if _local_tag(case.tag) != "testcase":
                continue
            name = case.get("name") or ""
            classname = case.get("classname") or ""
            display = f"{classname} {name}".strip() if classname else name
            failure = _child(case, "failure")
            error = _child(case, "error")
            skipped_el = _child(case, "skipped")
            detail = failure if failure is not None else error
            if detail is not None:
                status = "FAIL"
                message = detail.get("message") or (detail.text or "")
            elif skipped_el is not None:
                status = "SKIPPED"
                message = skipped_el.get("message") or (skipped_el.text or "")
            else:
                status = "PASS"
                message = ""
            cases.append({
                "name": display,
                "status": status,
                "message": (message or "").strip(),
                "time": case.get("time") or "",
                "alert_monitoring": is_alert_test(display),
            })

    if tests == 0:
        tests = len(cases)
    if failures == 0:
        failures = sum(1 for case in cases if case["status"] == "FAIL")
    if skipped == 0:
        skipped = sum(1 for case in cases if case["status"] == "SKIPPED")

    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "cases": cases,
    }


def empty_alert_monitoring(reason=ALERT_NOT_PRESENT_REASON):
    return {
        "status": "SKIP",
        "test_name": "",
        "skip_reason": reason,
    }


def alert_monitoring_from_cases(cases):
    alert_cases = [case for case in cases if case.get("alert_monitoring")]
    if not alert_cases:
        return empty_alert_monitoring()
    failed = [case for case in alert_cases if case["status"] == "FAIL"]
    names = [case["name"] for case in alert_cases]
    if failed:
        return {
            "status": "FAIL",
            "test_name": failed[0]["name"],
            "skip_reason": "",
            "failed_tests": [case["name"] for case in failed],
        }
    return {
        "status": "PASS",
        "test_name": names[0],
        "skip_reason": "",
        "matched_tests": names,
    }


def junit_source(snapshot):
    source = snapshot.get("source") or {}
    return {
        "job_name": source.get("job_name") or "",
        "build_id": source.get("build_id") or "",
        "test_name": source.get("test_name") or "",
        "job_result": source.get("job_result") or "",
        "gcs_url": source.get("gcs_url") or "",
    }


def evaluate_topology(topology, snapshot):
    parsed = parse_junit(snapshot["junit-rosa-e2e.xml"])
    failed_cases = [case for case in parsed["cases"] if case["status"] == "FAIL"]
    alert = alert_monitoring_from_cases(parsed["cases"])
    suite_failed = parsed["failures"] > 0 or parsed["errors"] > 0
    status = "FAIL" if failed_cases or suite_failed or alert["status"] == "FAIL" else "PASS"
    return {
        "topology": topology,
        "display_name": topology_display_name(topology),
        "status": status,
        "skip_reason": "",
        "source": junit_source(snapshot),
        "tests": parsed["tests"],
        "failures": parsed["failures"],
        "errors": parsed["errors"],
        "skipped": parsed["skipped"],
        "failed_cases": [
            {"name": case["name"], "message": case["message"]}
            for case in failed_cases
        ],
        "alert_monitoring": alert,
    }


def skip_topology(topology, reason):
    log_warning(f"{topology}: {reason}")
    return {
        "topology": topology,
        "display_name": topology_display_name(topology),
        "status": "SKIP",
        "skip_reason": reason,
        "source": {},
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "failed_cases": [],
        "alert_monitoring": empty_alert_monitoring(reason),
    }


def print_topology(result, verbose=False):
    topology = result.get("display_name") or result["topology"]
    if result["status"] == "SKIP":
        log_warning(f"  {topology}: SKIP ({result['skip_reason']})")
        return
    alert = result["alert_monitoring"]
    log_info(
        f"  {topology}: {result['status']} | "
        f"tests={result['tests']} failures={result['failures']} "
        f"skipped={result['skipped']} | alert monitoring={alert['status']}"
    )
    if alert["status"] == "SKIP":
        log_warning(f"    alert monitoring: SKIP ({alert['skip_reason']})")
    elif alert["status"] == "FAIL":
        log_warning(f"    alert monitoring: FAIL ({alert.get('test_name')})")
    if verbose:
        for case in result["failed_cases"]:
            log_warning(f"    FAIL {case['name']}")


def combined_summary(topology_results):
    compared = [result for result in topology_results if result["status"] != "SKIP"]
    coverage = topology_coverage_summary(topology_results, include_failed=True)
    summary = {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "failed_count": 0,
        **coverage,
        "alert_monitoring_pass": 0,
        "alert_monitoring_fail": 0,
        "alert_monitoring_skip": 0,
    }
    for result in compared:
        for key in ("tests", "failures", "errors", "skipped"):
            summary[key] += result.get(key, 0)
        summary["failed_count"] += len(result.get("failed_cases") or [])
        alert_status = (result.get("alert_monitoring") or {}).get("status")
        if alert_status == "PASS":
            summary["alert_monitoring_pass"] += 1
        elif alert_status == "FAIL":
            summary["alert_monitoring_fail"] += 1
        else:
            summary["alert_monitoring_skip"] += 1
    return summary


def overall_result(topology_results, summary):
    if any(result["status"] == "FAIL" for result in topology_results):
        failed = summary.get("failed_display_names") or summary["failed_topologies"]
        return "FAIL", (
            f"{summary['failed_count']} failed test(s) across {', '.join(failed) or 'target e2e'}"
        )
    compared = [result for result in topology_results if result["status"] != "SKIP"]
    if not compared:
        skipped = [result for result in topology_results if result["status"] == "SKIP"]
        return "SKIP", (
            "; ".join(result["skip_reason"] for result in skipped) or "no target e2e JUnit found"
        )
    message = (
        f"{summary['tests']} test(s), {summary['failures']} failure(s) "
        f"({', '.join(summary.get('compared_display_names') or summary['compared_topologies'])})"
    )
    if summary["alert_monitoring_skip"] and not summary["alert_monitoring_fail"]:
        message += "; alert monitoring SKIP (test not in rosa-e2e yet)"
    return "PASS", message


def main():
    parser = argparse.ArgumentParser(
        description="Validate target-version ROSA e2e JUnit and alert monitoring.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --baseline 4.21 --target 4.22
  %(prog)s --baseline 4.22 --target 5.0
  %(prog)s --junit /tmp/junit-rosa-e2e.xml --topology hcp --baseline 4.21 --target 4.22

Exit Codes:
  0 - Successful execution (informational; missing JUnit is SKIP;
      failed e2e tests are reported but do not fail the job)
  1 - Execution failure
        """,
    )
    parser.add_argument("--version", help="Single version to analyze (auto-resolves baseline and target)")
    parser.add_argument("--baseline", help="Baseline version (requires --target; only target JUnit is used)")
    parser.add_argument("--target", help="Target version (requires --baseline)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--report-dir", default=os.environ.get("REPORT_DIR", "reports"),
                        help="Directory to store reports")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show versions that would be used and exit")
    parser.add_argument("--topology", action="append", dest="topologies",
                        choices=list(TOPOLOGY_CHOICES),
                        help=TOPOLOGY_HELP)
    parser.add_argument("--junit", help="Local junit-rosa-e2e.xml file (requires exactly one --topology)")
    parser.add_argument("--target-dir", help="Local directory containing junit-rosa-e2e.xml")
    args = parser.parse_args()

    if args.junit and args.target_dir:
        log_error("--junit and --target-dir cannot be used together")
        sys.exit(1)

    baseline_full, target_full = resolve_gap_versions(
        version=args.version, baseline=args.baseline, target=args.target
    )
    baseline_minor = extract_minor_version(baseline_full)
    target_minor = extract_minor_version(target_full)
    topologies = tuple(args.topologies) if args.topologies else DEFAULT_TOPOLOGIES

    start_time = datetime.now()
    log_info(f"Starting {CHECK_NAME}")
    log_info("=========================================")
    log_info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_info(f"Baseline version: {baseline_full} (minor: {baseline_minor}) — not consumed")
    log_info(f"Target version: {target_full} (minor: {target_minor}) — JUnit source")
    log_info(f"Topologies: {', '.join(topologies)}")
    for topology in topologies:
        log_info(f"  {topology}: target {topology} {target_minor}")
    log_info("=========================================")

    if args.dry_run:
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    topology_results = []
    gcp_skip = osd_gcp_skip_reason(target_minor)
    local_path = args.junit or args.target_dir
    if local_path:
        if len(topologies) != 1:
            log_error("Local JUnit requires exactly one --topology")
            sys.exit(1)
        topology = topologies[0]
        if topology == "osd-gcp" and gcp_skip:
            topology_results.append(skip_topology(topology, gcp_skip))
        else:
            try:
                snapshot = load_e2e_junit_from_path(local_path)
                topology_results.append(evaluate_topology(topology, snapshot))
            except (OSError, ValueError, ET.ParseError) as err:
                topology_results.append(skip_topology(topology, str(err)))
    else:
        for topology in topologies:
            if topology == "osd-gcp" and gcp_skip:
                topology_results.append(skip_topology(topology, gcp_skip))
                continue
            snapshot = find_e2e_junit(target_minor, topology)
            if not snapshot:
                topology_results.append(skip_topology(
                    topology,
                    f"no target e2e JUnit found for {topology} {target_minor}",
                ))
                continue
            try:
                topology_results.append(evaluate_topology(topology, snapshot))
            except (OSError, ValueError, ET.ParseError) as err:
                topology_results.append(skip_topology(topology, str(err)))

    summary = combined_summary(topology_results)
    validation_result, status_message = overall_result(topology_results, summary)

    log_info(f"\nCHECK #{CHECK_NUMBER}: {CHECK_NAME}")
    for result in topology_results:
        print_topology(result, verbose=args.verbose)

    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)
    timestamp_suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    report_data = {
        "type": CHECK_NAME,
        "baseline": baseline_full,
        "target": target_full,
        "baseline_minor": baseline_minor,
        "target_minor": target_minor,
        "timestamp": datetime.now().isoformat(),
        "validation_result": validation_result,
        "topologies": topology_results,
        "summary": summary,
        "error_message": status_message,
        "note": NOTE,
    }

    json_file = os.path.join(
        report_dir,
        f"gap-analysis-{REPORT_SLUG}_{baseline_minor}_to_{target_minor}{timestamp_suffix}.json",
    )
    generate_json_report(report_data, json_file)
    log_info(f"JSON report generated: {json_file}")

    if not os.environ.get("GAP_FULL_REPORT"):
        html_file = os.path.join(
            report_dir,
            f"gap-analysis-{REPORT_SLUG}_{baseline_minor}_to_{target_minor}{timestamp_suffix}.html",
        )
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")
    else:
        log_info("Skipping HTML reports (full report will be generated)")

    log_success("=" * 60)
    if validation_result == "SKIP":
        log_warning(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [SKIP]")
        log_warning(f"  {status_message}")
    elif validation_result == "FAIL":
        log_warning(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [FAIL] (informational; does not fail the job)")
        log_warning(f"  {status_message}")
        for result in topology_results:
            for case in result.get("failed_cases") or []:
                log_warning(f"    • {result['topology']}: {case['name']}")
        log_success(f"✅ PASSED - {CHECK_NAME} analysis complete (informational)")
    else:
        log_success(f"✓ VALIDATION PASSED - {CHECK_NAME} (Informational)")
        log_success(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [PASS - Info]")
        log_success(f"  {status_message}")
        skipped = [result for result in topology_results if result["status"] == "SKIP"]
        if skipped:
            log_warning(f"  Skipped topologies: {', '.join(r.get('display_name') or r['topology'] for r in skipped)}")
        log_success(f"✅ PASSED - {CHECK_NAME} analysis complete (informational)")

    # Report FAIL stays in HTML/JSON for e2e quality. Status file uses WARNING
    # so exit_code is 0 and the orchestrator does not treat this as a job failure.
    status_for_orchestrator = "WARNING" if validation_result == "FAIL" else validation_result
    generate_status_report(
        check_number=CHECK_NUMBER,
        check_name=CHECK_NAME,
        status=status_for_orchestrator,
        details={
            "message": status_message,
            "differences_count": (
                max(summary["failed_count"], 1) if validation_result == "FAIL"
                else summary["failed_count"]
            ),
            "compared_topologies": summary["compared_topologies"],
            "skipped_topologies": summary["skipped_topologies"],
            "failed_topologies": summary["failed_topologies"],
        },
        report_dir=args.report_dir,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
