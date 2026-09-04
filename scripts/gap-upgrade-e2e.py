#!/usr/bin/env python3
"""Upgrade Validation from Y-1 to Y with E2E Tests - consume rosa-e2e upgrade jobs."""

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
    TOPOLOGY_CHOICES,
    UPGRADE_DEFAULT_TOPOLOGIES,
    UPGRADE_TOPOLOGY_HELP,
    find_upgrade_validation,
    load_e2e_junit_from_path,
    topology_coverage_summary,
    topology_display_name,
)
from reporters import generate_html_report, generate_json_report, generate_status_report

CHECK_NUMBER = 13
CHECK_NAME = "Upgrade Validation from Y-1 to Y with E2E Tests"
REPORT_SLUG = "upgrade-e2e"
DURATION_SKIP_REASON = (
    "upgrade duration not available "
    "(no upgrade-metrics.json or finished.json timestamps)"
)
PRE_UPGRADE_SKIP_REASON = (
    "pre-upgrade ClusterOperator snapshot is not published yet; "
    "cannot compute CO status changes across the upgrade"
)
POST_UPGRADE_SKIP_REASON = (
    "post-upgrade ClusterOperator snapshot not found in the upgrade job artifacts"
)
NOTE = (
    "Consumes existing rosa-e2e Y-1 → Y upgrade periodics "
    "(rosa-hcp-upgrade-staging-y-minus-1, "
    "rosa-classic-sts-upgrade-staging-y-minus-1, and "
    "osd-gcp-upgrade-staging-y-minus-1). Does not provision or "
    "upgrade clusters. Check #12 remains target-version fresh-install JUnit. "
    "Missing upgrade JUnit is SKIP. Failed post-upgrade e2e tests FAIL. "
    "Post-upgrade degraded or unavailable ClusterOperators FAIL when a "
    "JSON or oc-get txt snapshot is present. Builds whose post-upgrade "
    "minor does not match the resolved target are skipped. Duration comes "
    "from upgrade-metrics.json or finished.json timestamps. Pre-upgrade COs "
    "and CO deltas are used when the upgrade step published a before-snapshot; "
    "otherwise that subsection is SKIP."
)
CATEGORY_MARKERS = (
    ("storage", ("pvc", "persistentvolume", "storageclass", "volume", "csi")),
    ("network", ("network", "ingress", "connectivity", "dns", "ovn", "cni")),
    ("managed_operator", ("clusteroperator", "operator", "managed")),
    ("workload", ("pod", "deployment", "service", "route", "statefulset", "daemonset")),
)


def _local_tag(tag):
    return tag.rsplit("}", 1)[-1] if tag else ""


def _child(element, name):
    for child in list(element):
        if _local_tag(child.tag) == name:
            return child
    return None


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
                "categories": categorize_test(display),
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


def categorize_test(name):
    """Heuristic categories for post-upgrade workload / storage / network / operator tests."""
    lowered = (name or "").lower()
    matched = [
        category for category, markers in CATEGORY_MARKERS
        if any(marker in lowered for marker in markers)
    ]
    return matched or ["other"]


def operator_index(snapshot):
    items = ((snapshot or {}).get("clusteroperators.json") or {}).get("items") or []
    return {item.get("name"): item for item in items if item.get("name")}


def node_index(snapshot):
    items = ((snapshot or {}).get("nodes.json") or {}).get("items") or []
    return {item.get("name"): item for item in items if item.get("name")}


def junit_source(payload):
    source = (payload or {}).get("source") or {}
    return {
        "job_name": source.get("job_name") or "",
        "build_id": source.get("build_id") or "",
        "test_name": source.get("test_name") or "",
        "job_result": source.get("job_result") or "",
        "gcs_url": source.get("gcs_url") or "",
    }


def parse_upgrade_duration(metrics, metrics_url=""):
    if isinstance(metrics, dict) and metrics.get("status"):
        return metrics
    if not metrics:
        return {
            "status": "SKIP",
            "skip_reason": DURATION_SKIP_REASON,
            "duration": "",
            "source_url": metrics_url or "",
        }
    duration = ""
    for key in (
        "duration_seconds",
        "upgrade_duration_seconds",
        "duration",
        "elapsed_seconds",
    ):
        if metrics.get(key) is not None:
            duration = str(metrics.get(key))
            break
    return {
        "status": "INFO",
        "skip_reason": "",
        "duration": duration,
        "source_url": metrics_url or "",
    }


def operator_changes(pre_snapshot, post_snapshot):
    if not pre_snapshot or not post_snapshot:
        return {
            "newly_degraded": [],
            "newly_unavailable": [],
            "recovered_degraded": [],
            "recovered_unavailable": [],
        }
    pre_ops = operator_index(pre_snapshot)
    post_ops = operator_index(post_snapshot)
    pre_degraded = {name for name, item in pre_ops.items() if item.get("degraded") == "True"}
    post_degraded = {name for name, item in post_ops.items() if item.get("degraded") == "True"}
    pre_unavail = {name for name, item in pre_ops.items() if item.get("available") == "False"}
    post_unavail = {name for name, item in post_ops.items() if item.get("available") == "False"}
    return {
        "newly_degraded": sorted(post_degraded - pre_degraded),
        "newly_unavailable": sorted(post_unavail - pre_unavail),
        "recovered_degraded": sorted(pre_degraded - post_degraded),
        "recovered_unavailable": sorted(pre_unavail - post_unavail),
    }


def post_upgrade_health(snapshot):
    if not snapshot:
        return {
            "status": "SKIP",
            "skip_reason": POST_UPGRADE_SKIP_REASON,
            "degraded": [],
            "unavailable": [],
            "notready_nodes": [],
            "operator_count": 0,
            "node_count": 0,
            "overall_status": "",
            "cluster_version": "",
        }
    ops = operator_index(snapshot)
    nodes = node_index(snapshot)
    degraded = sorted(name for name, item in ops.items() if item.get("degraded") == "True")
    unavailable = sorted(name for name, item in ops.items() if item.get("available") == "False")
    notready = sorted(name for name, item in nodes.items() if item.get("ready") != "True")
    meta = snapshot.get("metadata.json") or {}
    unhealthy = bool(degraded or unavailable)
    return {
        "status": "FAIL" if unhealthy else "PASS",
        "skip_reason": "",
        "degraded": degraded,
        "unavailable": unavailable,
        "notready_nodes": notready,
        "operator_count": len(ops),
        "node_count": meta.get("node_count") or len(nodes),
        "overall_status": meta.get("overall_status") or "",
        "cluster_version": meta.get("cluster_version") or "",
        "source_url": (snapshot.get("source") or {}).get("gcs_url") or "",
    }


def pre_upgrade_health(pre_snapshot, post_snapshot):
    if not pre_snapshot:
        return {
            "status": "SKIP",
            "skip_reason": PRE_UPGRADE_SKIP_REASON,
            "degraded": [],
            "unavailable": [],
            "changes": operator_changes(None, None),
            "cluster_version": "",
        }
    health = post_upgrade_health(pre_snapshot)
    health["skip_reason"] = ""
    health["changes"] = operator_changes(pre_snapshot, post_snapshot)
    health["cluster_version"] = (pre_snapshot.get("metadata.json") or {}).get("cluster_version") or ""
    return health


def category_summary(failed_cases):
    counts = {
        "workload": 0,
        "storage": 0,
        "network": 0,
        "managed_operator": 0,
        "other": 0,
    }
    for case in failed_cases:
        for category in case.get("categories") or ["other"]:
            if category in counts:
                counts[category] += 1
    return counts


def evaluate_topology(topology, payload):
    junit = payload.get("junit") or payload
    parsed = parse_junit(junit["junit-rosa-e2e.xml"])
    failed_cases = [case for case in parsed["cases"] if case["status"] == "FAIL"]
    duration = parse_upgrade_duration(
        payload.get("duration") or payload.get("upgrade_metrics"),
        payload.get("upgrade_metrics_url") or "",
    )
    post_health = post_upgrade_health(payload.get("post_install"))
    pre_health = pre_upgrade_health(payload.get("pre_install"), payload.get("post_install"))
    suite_failed = parsed["failures"] > 0 or parsed["errors"] > 0
    status = "FAIL" if (
        failed_cases or suite_failed
        or post_health["status"] == "FAIL"
        or pre_health["status"] == "FAIL"
    ) else "PASS"
    return {
        "topology": topology,
        "display_name": topology_display_name(topology),
        "status": status,
        "skip_reason": "",
        "source": junit_source(junit),
        "tests": parsed["tests"],
        "failures": parsed["failures"],
        "errors": parsed["errors"],
        "skipped": parsed["skipped"],
        "failed_cases": [
            {
                "name": case["name"],
                "message": case["message"],
                "categories": case.get("categories") or ["other"],
            }
            for case in failed_cases
        ],
        "e2e_categories": category_summary(failed_cases),
        "duration": duration,
        "pre_upgrade_operators": pre_health,
        "post_upgrade_operators": post_health,
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
        "e2e_categories": category_summary([]),
        "duration": {
            "status": "SKIP",
            "skip_reason": reason,
            "duration": "",
            "source_url": "",
        },
        "pre_upgrade_operators": {
            "status": "SKIP",
            "skip_reason": reason,
            "degraded": [],
            "unavailable": [],
            "changes": operator_changes(None, None),
            "cluster_version": "",
        },
        "post_upgrade_operators": {
            "status": "SKIP",
            "skip_reason": reason,
            "degraded": [],
            "unavailable": [],
            "notready_nodes": [],
            "operator_count": 0,
            "node_count": 0,
            "overall_status": "",
            "cluster_version": "",
        },
    }


def print_topology(result, verbose=False):
    topology = result.get("display_name") or result["topology"]
    if result["status"] == "SKIP":
        log_warning(f"  {topology}: SKIP ({result['skip_reason']})")
        return
    duration = result.get("duration") or {}
    post = result.get("post_upgrade_operators") or {}
    log_info(
        f"  {topology}: {result['status']} | "
        f"tests={result['tests']} failures={result['failures']} "
        f"skipped={result['skipped']} | duration={duration.get('status')} | "
        f"post-upgrade COs={post.get('status')}"
    )
    if duration.get("status") == "SKIP":
        log_warning(f"    duration: SKIP ({duration.get('skip_reason')})")
    elif duration.get("duration"):
        log_info(f"    duration: {duration.get('duration')}")
    pre = result.get("pre_upgrade_operators") or {}
    if pre.get("status") == "SKIP":
        log_warning(f"    pre-upgrade COs: SKIP ({pre.get('skip_reason')})")
    elif pre.get("status") == "FAIL":
        log_error(
            f"    pre-upgrade COs: FAIL degraded={pre.get('degraded')} "
            f"unavailable={pre.get('unavailable')}"
        )
    else:
        log_info(
            f"    pre-upgrade COs: PASS version={pre.get('cluster_version') or 'unknown'}"
        )
        changes = pre.get("changes") or {}
        if changes.get("newly_degraded") or changes.get("newly_unavailable"):
            log_error(
                f"    CO changes: newly degraded={changes.get('newly_degraded')} "
                f"newly unavailable={changes.get('newly_unavailable')}"
            )
    if post.get("status") == "SKIP":
        log_warning(f"    post-upgrade COs: SKIP ({post.get('skip_reason')})")
    elif post.get("status") == "FAIL":
        log_error(
            f"    post-upgrade COs: FAIL degraded={post.get('degraded')} "
            f"unavailable={post.get('unavailable')}"
        )
    if verbose:
        for case in result["failed_cases"]:
            log_error(f"    FAIL {case['name']}")


def combined_summary(topology_results):
    compared = [result for result in topology_results if result["status"] != "SKIP"]
    coverage = topology_coverage_summary(topology_results, include_failed=True)
    summary = {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "failed_count": 0,
        "degraded_operators": 0,
        "unavailable_operators": 0,
        "duration_skip": 0,
        "pre_upgrade_skip": 0,
        "post_upgrade_fail": 0,
        **coverage,
        "e2e_categories": category_summary([]),
    }
    for result in compared:
        for key in ("tests", "failures", "errors", "skipped"):
            summary[key] += result.get(key, 0)
        summary["failed_count"] += len(result.get("failed_cases") or [])
        post = result.get("post_upgrade_operators") or {}
        summary["degraded_operators"] += len(post.get("degraded") or [])
        summary["unavailable_operators"] += len(post.get("unavailable") or [])
        if post.get("status") == "FAIL":
            summary["post_upgrade_fail"] += 1
        cats = result.get("e2e_categories") or {}
        for key in summary["e2e_categories"]:
            summary["e2e_categories"][key] += cats.get(key, 0)
    for result in topology_results:
        if (result.get("duration") or {}).get("status") == "SKIP":
            summary["duration_skip"] += 1
        if (result.get("pre_upgrade_operators") or {}).get("status") == "SKIP":
            summary["pre_upgrade_skip"] += 1
    return summary


def overall_result(topology_results, summary):
    if any(result["status"] == "FAIL" for result in topology_results):
        failed = summary.get("failed_display_names") or summary["failed_topologies"]
        parts = []
        if summary["failed_count"]:
            parts.append(f"{summary['failed_count']} failed test(s)")
        if summary["post_upgrade_fail"]:
            parts.append(
                f"{summary['degraded_operators']} degraded / "
                f"{summary['unavailable_operators']} unavailable ClusterOperator(s)"
            )
        return "FAIL", (
            f"{'; '.join(parts) or 'upgrade validation failed'} "
            f"across {', '.join(failed) or 'upgrade e2e'}"
        )
    compared = [result for result in topology_results if result["status"] != "SKIP"]
    if not compared:
        skipped = [result for result in topology_results if result["status"] == "SKIP"]
        return "SKIP", (
            "; ".join(result["skip_reason"] for result in skipped)
            or "no Y-1 → Y upgrade JUnit found"
        )
    message = (
        f"{summary['tests']} test(s), {summary['failures']} failure(s) "
        f"({', '.join(summary.get('compared_display_names') or summary['compared_topologies'])})"
    )
    if summary["duration_skip"]:
        message += "; upgrade duration SKIP"
    if summary["pre_upgrade_skip"]:
        message += "; pre-upgrade COs SKIP"
    return "PASS", message


def local_payload(path):
    junit = load_e2e_junit_from_path(path)
    return {
        "junit": junit,
        "post_install": None,
        "pre_install": None,
        "duration": {
            "status": "SKIP",
            "skip_reason": DURATION_SKIP_REASON,
            "duration": "",
            "source_url": "",
        },
        "upgrade_metrics": None,
        "upgrade_metrics_url": "",
        "source": junit.get("source") or {},
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate Y-1 → Y ROSA upgrades from existing rosa-e2e upgrade periodics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --baseline 4.21 --target 4.22
  %(prog)s --version 4.22
  %(prog)s --junit /tmp/junit-rosa-e2e.xml --topology hcp --baseline 4.21 --target 4.22

Exit Codes:
  0 - PASS or SKIP (missing upgrade JUnit)
  1 - FAIL (post-upgrade e2e failures or unhealthy ClusterOperators) or execution error
        """,
    )
    parser.add_argument("--version", help="Single version to analyze (auto-resolves baseline and target)")
    parser.add_argument("--baseline", help="Baseline version (Y-1; requires --target)")
    parser.add_argument("--target", help="Target version Y (requires --baseline)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--report-dir", default=os.environ.get("REPORT_DIR", "reports"),
                        help="Directory to store reports")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show versions that would be used and exit")
    parser.add_argument("--topology", action="append", dest="topologies",
                        choices=list(TOPOLOGY_CHOICES),
                        help=UPGRADE_TOPOLOGY_HELP)
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
    topologies = tuple(args.topologies) if args.topologies else UPGRADE_DEFAULT_TOPOLOGIES

    start_time = datetime.now()
    log_info(f"Starting {CHECK_NAME}")
    log_info("=========================================")
    log_info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_info(f"Baseline version (Y-1): {baseline_full} (minor: {baseline_minor})")
    log_info(f"Target version (Y): {target_full} (minor: {target_minor})")
    log_info(f"Topologies: {', '.join(topologies)}")
    log_info("=========================================")

    if args.dry_run:
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    topology_results = []
    local_path = args.junit or args.target_dir
    if local_path:
        if len(topologies) != 1:
            log_error("Local JUnit requires exactly one --topology")
            sys.exit(1)
        topology = topologies[0]
        try:
            topology_results.append(evaluate_topology(topology, local_payload(local_path)))
        except (OSError, ValueError, ET.ParseError) as err:
            topology_results.append(skip_topology(topology, str(err)))
    else:
        for topology in topologies:
            payload = find_upgrade_validation(target_minor, topology)
            if not payload:
                topology_results.append(skip_topology(
                    topology,
                    f"no Y-1 → Y upgrade JUnit found for {topology} "
                    f"(target minor {target_minor})",
                ))
                continue
            try:
                topology_results.append(evaluate_topology(topology, payload))
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
        log_error(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [FAIL]")
        log_error(f"  {status_message}")
        for result in topology_results:
            for case in result.get("failed_cases") or []:
                log_error(f"    • {result['topology']}: {case['name']}")
            post = result.get("post_upgrade_operators") or {}
            for name in post.get("degraded") or []:
                log_error(f"    • {result['topology']}: degraded ClusterOperator {name}")
            for name in post.get("unavailable") or []:
                log_error(f"    • {result['topology']}: unavailable ClusterOperator {name}")
    else:
        log_success(f"✓ VALIDATION PASSED - {CHECK_NAME}")
        log_success(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [PASS]")
        log_success(f"  {status_message}")
        skipped = [result for result in topology_results if result["status"] == "SKIP"]
        if skipped:
            log_warning(
                f"  Skipped topologies: "
                f"{', '.join(r.get('display_name') or r['topology'] for r in skipped)}"
            )

    generate_status_report(
        check_number=CHECK_NUMBER,
        check_name=CHECK_NAME,
        status=validation_result,
        details={
            "message": status_message,
            "differences_count": summary["failed_count"] + summary["degraded_operators"]
            + summary["unavailable_operators"],
            "compared_topologies": summary["compared_topologies"],
            "skipped_topologies": summary["skipped_topologies"],
            "failed_topologies": summary["failed_topologies"],
        },
        report_dir=args.report_dir,
    )
    sys.exit(1 if validation_result == "FAIL" else 0)


if __name__ == "__main__":
    main()
