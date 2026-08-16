#!/usr/bin/env python3
"""Cluster Install and Delete Validation - compare live ROSA install-health snapshots."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from common import log_error, log_info, log_success, log_warning
from openshift_releases import extract_minor_version, resolve_gap_versions
from prow_artifacts import (
    DEFAULT_TOPOLOGIES,
    TOPOLOGY_CHOICES,
    TOPOLOGY_HELP,
    find_cluster_install_snapshot,
    iter_snapshot_role_results,
    load_cluster_install_snapshot,
    osd_gcp_skip_reason,
    topology_coverage_summary,
    topology_display_name,
    topology_pair_label,
)
from reporters import generate_html_report, generate_json_report, generate_status_report

CHECK_NUMBER = 11
CHECK_NAME = "Cluster Install and Delete Validation"
REPORT_SLUG = "cluster-install"


def operator_index(snapshot):
    items = (snapshot.get("clusteroperators.json") or {}).get("items") or []
    return {item.get("name"): item for item in items if item.get("name")}


def node_index(snapshot):
    items = (snapshot.get("nodes.json") or {}).get("items") or []
    return {item.get("name"): item for item in items if item.get("name")}


def meta(snapshot):
    return snapshot.get("metadata.json") or {}


def empty_cluster_install_comparison():
    return {
        "new_operators": [],
        "removed_operators": [],
        "newly_degraded": [],
        "newly_unavailable": [],
        "recovered_degraded": [],
        "recovered_unavailable": [],
        "newly_notready_nodes": [],
        "node_count_baseline": 0,
        "node_count_target": 0,
        "overall_status_baseline": "",
        "overall_status_target": "",
    }


def compare_cluster_install(baseline, target):
    base_ops = operator_index(baseline)
    dest_ops = operator_index(target)
    base_meta = meta(baseline)
    dest_meta = meta(target)

    new_operators = sorted(set(dest_ops) - set(base_ops))
    removed_operators = sorted(set(base_ops) - set(dest_ops))

    base_degraded = {name for name, item in base_ops.items() if item.get("degraded") == "True"}
    dest_degraded = {name for name, item in dest_ops.items() if item.get("degraded") == "True"}
    base_unavailable = {name for name, item in base_ops.items() if item.get("available") == "False"}
    dest_unavailable = {name for name, item in dest_ops.items() if item.get("available") == "False"}

    base_nodes = node_index(baseline)
    dest_nodes = node_index(target)
    base_notready = {name for name, item in base_nodes.items() if item.get("ready") != "True"}
    dest_notready = {name for name, item in dest_nodes.items() if item.get("ready") != "True"}

    return {
        "new_operators": new_operators,
        "removed_operators": removed_operators,
        "newly_degraded": sorted(dest_degraded - base_degraded),
        "newly_unavailable": sorted(dest_unavailable - base_unavailable),
        "recovered_degraded": sorted(base_degraded - dest_degraded),
        "recovered_unavailable": sorted(base_unavailable - dest_unavailable),
        "newly_notready_nodes": sorted(dest_notready - base_notready),
        "node_count_baseline": base_meta.get("node_count") or len(base_nodes),
        "node_count_target": dest_meta.get("node_count") or len(dest_nodes),
        "overall_status_baseline": base_meta.get("overall_status") or "",
        "overall_status_target": dest_meta.get("overall_status") or "",
    }


def summarize_cluster_install(comparison):
    return {
        "new_operators": len(comparison["new_operators"]),
        "removed_operators": len(comparison["removed_operators"]),
        "newly_degraded": len(comparison["newly_degraded"]),
        "newly_unavailable": len(comparison["newly_unavailable"]),
        "recovered_degraded": len(comparison["recovered_degraded"]),
        "recovered_unavailable": len(comparison["recovered_unavailable"]),
        "newly_notready_nodes": len(comparison["newly_notready_nodes"]),
        "node_count_delta": (
            (comparison.get("node_count_target") or 0)
            - (comparison.get("node_count_baseline") or 0)
        ),
        "status_changed": (
            comparison.get("overall_status_baseline") != comparison.get("overall_status_target")
        ),
    }


def total_changes(summary):
    status_changed = summary.get("status_changed") or 0
    return (
        summary.get("new_operators", 0)
        + summary.get("removed_operators", 0)
        + summary.get("newly_degraded", 0)
        + summary.get("newly_unavailable", 0)
        + summary.get("newly_notready_nodes", 0)
        + int(status_changed)
    )


def cluster_install_source(snapshot):
    source = snapshot.get("source") or {}
    metadata = meta(snapshot)
    return {
        "job_name": source.get("job_name"),
        "build_id": source.get("build_id"),
        "gcs_url": source.get("gcs_url"),
        "cluster_version": metadata.get("cluster_version") or "",
        "openshift_version": metadata.get("openshift_version") or "",
        "captured_at": metadata.get("captured_at") or "",
        "cluster_id": metadata.get("cluster_id") or "",
        "topology": metadata.get("topology") or "",
        "cluster_role": metadata.get("cluster_role") or source.get("cluster_role") or "",
        "overall_status": metadata.get("overall_status") or "",
        "node_count": metadata.get("node_count"),
        "clusteroperator_count": metadata.get("clusteroperator_count"),
        "degraded_operators": metadata.get("degraded_operators") or [],
        "unavailable_operators": metadata.get("unavailable_operators") or [],
        "notready_nodes": metadata.get("notready_nodes") or [],
    }


def compare_cluster_install_topology(
    topology, baseline_snapshot, target_snapshot,
    baseline_topology=None, target_topology=None,
):
    comparison = compare_cluster_install(baseline_snapshot, target_snapshot)
    baseline_topology = baseline_topology or topology
    target_topology = target_topology or topology
    label = topology_pair_label(baseline_topology, target_topology)
    return {
        "topology": label,
        "display_name": topology_display_name(label),
        "baseline_topology": baseline_topology,
        "target_topology": target_topology,
        "status": "PASS",
        "skip_reason": "",
        "baseline": cluster_install_source(baseline_snapshot),
        "target": cluster_install_source(target_snapshot),
        "comparison": comparison,
        "summary": summarize_cluster_install(comparison),
    }


def skip_cluster_install_topology(
    topology, reason, baseline_topology=None, target_topology=None,
):
    log_warning(f"{topology}: {reason}")
    comparison = empty_cluster_install_comparison()
    baseline_topology = baseline_topology or topology
    target_topology = target_topology or topology
    label = topology_pair_label(baseline_topology, target_topology)
    return {
        "topology": label,
        "display_name": topology_display_name(label),
        "baseline_topology": baseline_topology,
        "target_topology": target_topology,
        "status": "SKIP",
        "skip_reason": reason,
        "baseline": {},
        "target": {},
        "comparison": comparison,
        "summary": summarize_cluster_install(comparison),
    }


def print_cluster_install_topology(result, verbose=False):
    topology = result.get("display_name") or result["topology"]
    if result["status"] == "SKIP":
        log_warning(f"  {topology}: SKIP ({result['skip_reason']})")
        return
    summary = result["summary"]
    comparison = result["comparison"]
    log_info(
        f"  {topology}: install {comparison['overall_status_baseline'] or '?'} → "
        f"{comparison['overall_status_target'] or '?'} | "
        f"+{summary['new_operators']} COs, -{summary['removed_operators']} COs, "
        f"{summary['newly_degraded']} newly degraded, "
        f"{summary['newly_unavailable']} newly unavailable, "
        f"nodes {comparison['node_count_baseline']} → {comparison['node_count_target']}"
    )
    if verbose:
        for name in result["comparison"]["newly_degraded"]:
            log_warning(f"    degraded {name}")
        for name in result["comparison"]["newly_unavailable"]:
            log_warning(f"    unavailable {name}")
        for name in result["comparison"]["new_operators"]:
            log_info(f"    + CO {name}")


def main():
    parser = argparse.ArgumentParser(
        description="Compare live ROSA cluster install health snapshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --baseline 4.21 --target 4.22
  %(prog)s --baseline 4.22 --target 5.0
  %(prog)s --baseline 4.22 --target 5.0 --topology classic

Exit Codes:
  0 - Successful execution (informational; missing snapshots are SKIP)
  1 - Execution failure
        """,
    )
    parser.add_argument("--version", help="Single version to analyze (auto-resolves baseline and target)")
    parser.add_argument("--baseline", help="Baseline version (requires --target)")
    parser.add_argument("--target", help="Target version (requires --baseline)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--report-dir", default=os.environ.get("REPORT_DIR", "reports"),
                        help="Directory to store reports")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show versions that would be used and exit")
    parser.add_argument("--topology", action="append", dest="topologies",
                        choices=list(TOPOLOGY_CHOICES),
                        help=TOPOLOGY_HELP)
    parser.add_argument("--baseline-dir", help="Local baseline snapshot directory (skips GCS)")
    parser.add_argument("--target-dir", help="Local target snapshot directory (skips GCS)")
    args = parser.parse_args()

    if bool(args.baseline_dir) != bool(args.target_dir):
        log_error("--baseline-dir and --target-dir must be used together")
        sys.exit(1)

    baseline_full, target_full = resolve_gap_versions(
        version=args.version, baseline=args.baseline, target=args.target
    )
    baseline_minor = extract_minor_version(baseline_full)
    target_minor = extract_minor_version(target_full)
    topologies = tuple(args.topologies) if args.topologies else DEFAULT_TOPOLOGIES

    start_time = datetime.now()
    log_info("Starting Cluster Install and Delete Validation")
    log_info("=========================================")
    log_info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_info(f"Baseline version: {baseline_full} (minor: {baseline_minor})")
    log_info(f"Target version: {target_full} (minor: {target_minor})")
    log_info(f"Topologies: {', '.join(topologies)}")
    for topology in topologies:
        log_info(f"  {topology}: {topology} {baseline_minor} → {topology} {target_minor}")
    log_info("=========================================")

    if args.dry_run:
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    topology_results = []
    gcp_skip = osd_gcp_skip_reason(baseline_minor, target_minor)
    if args.baseline_dir and args.target_dir:
        if len(topologies) != 1:
            log_error("Local snapshot dirs require exactly one --topology")
            sys.exit(1)
        topology = topologies[0]
        if topology == "osd-gcp" and gcp_skip:
            topology_results.append(skip_cluster_install_topology(
                topology, gcp_skip,
            ))
        else:
            try:
                baseline_snapshot = load_cluster_install_snapshot(args.baseline_dir)
                target_snapshot = load_cluster_install_snapshot(args.target_dir)
                for label, bsnap, tsnap, skip_reason in iter_snapshot_role_results(
                    topology, baseline_snapshot, target_snapshot, "Cluster Install",
                ):
                    if skip_reason:
                        topology_results.append(skip_cluster_install_topology(
                            label, skip_reason,
                        ))
                        continue
                    topology_results.append(
                        compare_cluster_install_topology(
                            label, bsnap, tsnap,
                        )
                    )
            except (OSError, ValueError, json.JSONDecodeError) as err:
                topology_results.append(skip_cluster_install_topology(
                    topology, str(err),
                ))
    else:
        for topology in topologies:
            if topology == "osd-gcp" and gcp_skip:
                topology_results.append(skip_cluster_install_topology(
                    topology, gcp_skip,
                ))
                continue
            baseline_snapshot = find_cluster_install_snapshot(baseline_minor, topology)
            target_snapshot = find_cluster_install_snapshot(target_minor, topology)
            for label, bsnap, tsnap, skip_reason in iter_snapshot_role_results(
                topology, baseline_snapshot, target_snapshot, "Cluster Install",
                baseline_minor=baseline_minor, target_minor=target_minor,
            ):
                if skip_reason:
                    topology_results.append(skip_cluster_install_topology(
                        label, skip_reason,
                    ))
                    continue
                topology_results.append(
                    compare_cluster_install_topology(
                        label, bsnap, tsnap,
                    )
                )

    compared = [result for result in topology_results if result["status"] != "SKIP"]
    skipped = [result for result in topology_results if result["status"] == "SKIP"]
    coverage = topology_coverage_summary(topology_results)

    combined_summary = {
        "new_operators": 0,
        "removed_operators": 0,
        "newly_degraded": 0,
        "newly_unavailable": 0,
        "recovered_degraded": 0,
        "recovered_unavailable": 0,
        "newly_notready_nodes": 0,
        "status_changed": 0,
        **coverage,
    }
    for result in compared:
        for key in (
            "new_operators", "removed_operators", "newly_degraded", "newly_unavailable",
            "recovered_degraded", "recovered_unavailable", "newly_notready_nodes",
        ):
            combined_summary[key] += result["summary"].get(key, 0)
        if result["summary"].get("status_changed"):
            combined_summary["status_changed"] += 1

    if not compared:
        validation_result = "SKIP"
        status_message = "; ".join(result["skip_reason"] for result in skipped) or "no snapshots found"
    else:
        validation_result = "PASS"
        changes = total_changes(combined_summary)
        if changes == 0:
            status_message = f"no install-health changes ({', '.join(combined_summary['compared_display_names'])})"
        else:
            status_message = (
                f"{changes} change(s) across {', '.join(combined_summary['compared_display_names'])}; "
                f"degraded={combined_summary['newly_degraded']} "
                f"unavailable={combined_summary['newly_unavailable']}"
            )

    log_info(f"\nCHECK #{CHECK_NUMBER}: {CHECK_NAME}")
    for result in topology_results:
        print_cluster_install_topology(result, verbose=args.verbose)

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
        "summary": combined_summary,
        "error_message": status_message,
        "note": (
            "Informational check. Snapshots come from live HCP, Classic, and OSD GCP cluster "
            "install health (ClusterOperators and nodes). The current CI step captures install "
            "health before deprovision; delete-duration metrics are not in the snapshot yet. "
            "Each topology is compared to itself. HCP also compares management-cluster "
            "install health (control plane) when ARTIFACT_DIR/management/ is present. "
            "OSD GCP is skipped for OpenShift 5.x (AWS/STS-only)."
        ),
    }

    json_file = os.path.join(
        report_dir,
        f"gap-analysis-{REPORT_SLUG}_{baseline_minor}_to_{target_minor}{timestamp_suffix}.json",
    )
    generate_json_report(report_data, json_file)
    log_info(f"JSON report generated: {json_file}")

    # Skip HTML when GAP_FULL_REPORT is set (combined report includes this check)
    if os.environ.get("GAP_FULL_REPORT"):
        log_info("Skipping HTML reports (full report will be generated)")
    else:
        html_file = os.path.join(
            report_dir,
            f"gap-analysis-{REPORT_SLUG}_{baseline_minor}_to_{target_minor}{timestamp_suffix}.html",
        )
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    log_success("=" * 60)
    if validation_result == "SKIP":
        log_warning(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [SKIP]")
        log_warning(f"  {status_message}")
        log_warning("  Snapshots come from live HCP, Classic, and OSD GCP cluster install health.")
    else:
        log_success(f"✓ VALIDATION PASSED - {CHECK_NAME} (Informational)")
        log_success("=" * 60)
        log_success(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [PASS - Info]")
        log_success(f"  {status_message}")
        if combined_summary["newly_degraded"]:
            log_warning(f"    • {combined_summary['newly_degraded']} newly degraded ClusterOperator(s)")
        if combined_summary["newly_unavailable"]:
            log_warning(f"    • {combined_summary['newly_unavailable']} newly unavailable ClusterOperator(s)")
        if combined_summary["new_operators"]:
            log_success(f"    • {combined_summary['new_operators']} new ClusterOperator(s)")
        if skipped:
            log_warning(f"  Skipped topologies: {', '.join(r.get('display_name') or r['topology'] for r in skipped)}")
        log_success(f"✅ PASSED - {CHECK_NAME} analysis complete (informational)")

    generate_status_report(
        check_number=CHECK_NUMBER,
        check_name=CHECK_NAME,
        status=validation_result,
        details={
            "message": status_message,
            "differences_count": total_changes(combined_summary),
            "compared_topologies": combined_summary["compared_topologies"],
            "skipped_topologies": combined_summary["skipped_topologies"],
        },
        report_dir=args.report_dir,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
