#!/usr/bin/env python3
"""API Resources and CRD Gap Analysis - compare live ROSA API Resources and CRD snapshots."""

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
    find_api_resources_and_crd_snapshot,
    iter_snapshot_role_results,
    load_api_resources_and_crd_snapshot,
    osd_gcp_skip_reason,
    topology_coverage_summary,
    topology_display_name,
    topology_pair_label,
)
from reporters import generate_html_report, generate_json_report, generate_status_report

CHECK_NUMBER = 9
CHECK_NAME = "API Resources and CRD Diff Validation"
REPORT_SLUG = "api-resources"
MANAGED_GROUP_SUFFIXES = (".openshift.io", ".coreos.com", ".openshift.com")


def is_managed_group(group):
    """True when an API group is likely relevant to managed OpenShift services."""
    group = group or ""
    return any(group.endswith(suffix) for suffix in MANAGED_GROUP_SUFFIXES)


def resource_identity(resource):
    group = resource.get("group") or ""
    name = resource.get("name") or ""
    return f"{group}/{name}" if group else name


def preferred_api_resources(snapshot):
    resources = (snapshot.get("api-resources.json") or {}).get("resources") or []
    preferred = [r for r in resources if r.get("preferred", True)]
    return {resource_identity(r): r for r in preferred if r.get("name")}


def all_api_resource_versions(snapshot):
    """Map identity -> sorted list of served versions."""
    resources = (snapshot.get("api-resources.json") or {}).get("resources") or []
    versions = {}
    for resource in resources:
        identity = resource_identity(resource)
        if not identity:
            continue
        versions.setdefault(identity, set()).add(resource.get("version") or "")
    return {key: sorted(value) for key, value in versions.items()}


def crd_index(snapshot):
    items = (snapshot.get("crds.json") or {}).get("items") or []
    return {item.get("name"): item for item in items if item.get("name")}


def crd_purpose(crd):
    names = crd.get("names") or {}
    kind = names.get("kind") or crd.get("name")
    group = crd.get("group") or ""
    scope = crd.get("scope") or ""
    parts = [kind]
    if group:
        parts.append(f"group={group}")
    if scope:
        parts.append(f"scope={scope}")
    return ", ".join(parts)


def crd_versions(crd):
    return [v.get("name") for v in (crd.get("versions") or []) if v.get("name")]


def crd_storage_version(crd):
    for version in crd.get("versions") or []:
        if version.get("storage"):
            return version.get("name")
    return None


def crd_deprecated_versions(crd):
    deprecated = []
    for version in crd.get("versions") or []:
        if version.get("deprecated"):
            deprecated.append({
                "version": version.get("name"),
                "warning": version.get("deprecationWarning") or "",
            })
    return deprecated


def compare_api_resources_and_crd(baseline, target):
    """Compare two API Resources and CRD snapshots and return structured diffs."""
    base_pref = preferred_api_resources(baseline)
    target_pref = preferred_api_resources(target)
    base_ids = set(base_pref)
    target_ids = set(target_pref)

    new_apis = []
    for identity in sorted(target_ids - base_ids):
        resource = target_pref[identity]
        new_apis.append({
            "id": identity,
            "group": resource.get("group") or "",
            "version": resource.get("version") or "",
            "kind": resource.get("kind") or "",
            "name": resource.get("name") or "",
            "namespaced": resource.get("namespaced", False),
            "managed_service": is_managed_group(resource.get("group") or ""),
        })

    removed_apis = []
    for identity in sorted(base_ids - target_ids):
        resource = base_pref[identity]
        removed_apis.append({
            "id": identity,
            "group": resource.get("group") or "",
            "version": resource.get("version") or "",
            "kind": resource.get("kind") or "",
            "name": resource.get("name") or "",
            "namespaced": resource.get("namespaced", False),
            "managed_service": is_managed_group(resource.get("group") or ""),
        })

    base_versions = all_api_resource_versions(baseline)
    target_versions = all_api_resource_versions(target)
    version_changes = []
    for identity in sorted(base_ids & target_ids):
        before = base_versions.get(identity, [])
        after = target_versions.get(identity, [])
        if before == after:
            continue
        resource = target_pref[identity]
        version_changes.append({
            "id": identity,
            "kind": resource.get("kind") or "",
            "group": resource.get("group") or "",
            "baseline_versions": before,
            "target_versions": after,
            "added_versions": sorted(set(after) - set(before)),
            "removed_versions": sorted(set(before) - set(after)),
            "preferred_baseline": base_pref[identity].get("version") or "",
            "preferred_target": resource.get("version") or "",
            "managed_service": is_managed_group(resource.get("group") or ""),
        })

    base_crds = crd_index(baseline)
    target_crds = crd_index(target)
    new_crds = []
    for name in sorted(set(target_crds) - set(base_crds)):
        crd = target_crds[name]
        new_crds.append({
            "name": name,
            "purpose": crd_purpose(crd),
            "group": crd.get("group") or "",
            "kind": (crd.get("names") or {}).get("kind") or "",
            "scope": crd.get("scope") or "",
            "versions": crd_versions(crd),
            "storage_version": crd_storage_version(crd),
            "managed_service": is_managed_group(crd.get("group") or ""),
        })

    removed_crds = []
    for name in sorted(set(base_crds) - set(target_crds)):
        crd = base_crds[name]
        removed_crds.append({
            "name": name,
            "purpose": crd_purpose(crd),
            "group": crd.get("group") or "",
            "kind": (crd.get("names") or {}).get("kind") or "",
            "scope": crd.get("scope") or "",
            "versions": crd_versions(crd),
            "managed_service": is_managed_group(crd.get("group") or ""),
        })

    crd_version_changes = []
    deprecated = []
    for name in sorted(set(base_crds) & set(target_crds)):
        before = base_crds[name]
        after = target_crds[name]
        before_versions = crd_versions(before)
        after_versions = crd_versions(after)
        before_storage = crd_storage_version(before)
        after_storage = crd_storage_version(after)
        added_versions = sorted(set(after_versions) - set(before_versions))
        removed_versions = sorted(set(before_versions) - set(after_versions))
        if added_versions or removed_versions or before_storage != after_storage:
            crd_version_changes.append({
                "name": name,
                "purpose": crd_purpose(after),
                "group": after.get("group") or "",
                "added_versions": added_versions,
                "removed_versions": removed_versions,
                "storage_baseline": before_storage,
                "storage_target": after_storage,
                "managed_service": is_managed_group(after.get("group") or ""),
            })

        newly_deprecated = []
        baseline_deprecated = {item["version"] for item in crd_deprecated_versions(before)}
        for item in crd_deprecated_versions(after):
            if item["version"] not in baseline_deprecated:
                newly_deprecated.append(item)
        if newly_deprecated:
            deprecated.append({
                "name": name,
                "purpose": crd_purpose(after),
                "group": after.get("group") or "",
                "versions": newly_deprecated,
                "managed_service": is_managed_group(after.get("group") or ""),
            })

    return {
        "new_api_resources": new_apis,
        "removed_api_resources": removed_apis,
        "api_version_changes": version_changes,
        "new_crds": new_crds,
        "removed_crds": removed_crds,
        "crd_version_changes": crd_version_changes,
        "deprecated_crds": deprecated,
    }


def summarize_api_resources_and_crd(comparison):
    return {
        "new_api_resources": len(comparison["new_api_resources"]),
        "removed_api_resources": len(comparison["removed_api_resources"]),
        "api_version_changes": len(comparison["api_version_changes"]),
        "new_crds": len(comparison["new_crds"]),
        "removed_crds": len(comparison["removed_crds"]),
        "crd_version_changes": len(comparison["crd_version_changes"]),
        "deprecated_crds": len(comparison["deprecated_crds"]),
        "managed_new_crds": sum(1 for item in comparison["new_crds"] if item["managed_service"]),
        "managed_deprecated_crds": sum(1 for item in comparison["deprecated_crds"] if item["managed_service"]),
        "managed_removed_apis": sum(1 for item in comparison["removed_api_resources"] if item["managed_service"]),
    }


def total_changes(summary):
    return (
        summary.get("new_api_resources", 0)
        + summary.get("removed_api_resources", 0)
        + summary.get("api_version_changes", 0)
        + summary.get("new_crds", 0)
        + summary.get("removed_crds", 0)
        + summary.get("crd_version_changes", 0)
        + summary.get("deprecated_crds", 0)
    )


def api_resources_and_crd_source(snapshot):
    source = snapshot.get("source") or {}
    meta = snapshot.get("metadata.json") or {}
    return {
        "job_name": source.get("job_name"),
        "build_id": source.get("build_id"),
        "gcs_url": source.get("gcs_url"),
        "cluster_version": meta.get("cluster_version") or "",
        "openshift_version": meta.get("openshift_version") or "",
        "captured_at": meta.get("captured_at") or "",
        "cluster_id": meta.get("cluster_id") or "",
        "topology": meta.get("topology") or "",
        "cluster_role": meta.get("cluster_role") or source.get("cluster_role") or "",
        "api_resource_count": meta.get("api_resource_count"),
        "crd_count": meta.get("crd_count"),
    }


def compare_api_resources_and_crd_topology(
    topology, baseline_snapshot, target_snapshot,
    baseline_topology=None, target_topology=None,
):
    comparison = compare_api_resources_and_crd(baseline_snapshot, target_snapshot)
    summary = summarize_api_resources_and_crd(comparison)
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
        "baseline": api_resources_and_crd_source(baseline_snapshot),
        "target": api_resources_and_crd_source(target_snapshot),
        "comparison": comparison,
        "summary": summary,
    }


def skip_api_resources_and_crd_topology(
    topology, reason, baseline_topology=None, target_topology=None,
):
    log_warning(f"{topology}: {reason}")
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
        "comparison": {
            "new_api_resources": [],
            "removed_api_resources": [],
            "api_version_changes": [],
            "new_crds": [],
            "removed_crds": [],
            "crd_version_changes": [],
            "deprecated_crds": [],
        },
        "summary": summarize_api_resources_and_crd({
            "new_api_resources": [],
            "removed_api_resources": [],
            "api_version_changes": [],
            "new_crds": [],
            "removed_crds": [],
            "crd_version_changes": [],
            "deprecated_crds": [],
        }),
    }


def print_api_resources_and_crd_topology(result, verbose=False):
    topology = result.get("display_name") or result["topology"]
    if result["status"] == "SKIP":
        log_warning(f"  {topology}: SKIP ({result['skip_reason']})")
        return

    summary = result["summary"]
    log_info(f"  {topology}: +{summary['new_api_resources']} APIs, -{summary['removed_api_resources']} APIs, "
             f"+{summary['new_crds']} CRDs, -{summary['removed_crds']} CRDs, "
             f"{summary['api_version_changes'] + summary['crd_version_changes']} version changes, "
             f"{summary['deprecated_crds']} newly deprecated")
    if verbose:
        for item in result["comparison"]["new_crds"]:
            marker = " [managed]" if item["managed_service"] else ""
            log_info(f"    + CRD {item['name']} ({item['purpose']}){marker}")
        for item in result["comparison"]["new_api_resources"]:
            marker = " [managed]" if item["managed_service"] else ""
            log_info(f"    + API {item['id']} {item['kind']}@{item['version']}{marker}")
        for item in result["comparison"]["deprecated_crds"]:
            versions = ", ".join(v["version"] for v in item["versions"])
            marker = " [managed]" if item["managed_service"] else ""
            log_info(f"    ! deprecated {item['name']} versions={versions}{marker}")


def main():
    parser = argparse.ArgumentParser(
        description="Compare live ROSA API Resources and CRD snapshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --version 4.22
  %(prog)s --baseline 4.21 --target 4.22
  %(prog)s --baseline 4.22 --target 5.0
  %(prog)s --version 5.0
  %(prog)s --baseline 4.22 --target 5.0 --topology classic
  %(prog)s --baseline-dir /tmp/base --target-dir /tmp/target --topology hcp

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
    log_info("Starting API Resources and CRD Gap Analysis")
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
            topology_results.append(skip_api_resources_and_crd_topology(
                topology, gcp_skip,
            ))
        else:
            try:
                baseline_snapshot = load_api_resources_and_crd_snapshot(args.baseline_dir)
                target_snapshot = load_api_resources_and_crd_snapshot(args.target_dir)
                for label, bsnap, tsnap, skip_reason in iter_snapshot_role_results(
                    topology, baseline_snapshot, target_snapshot, "API Resources and CRD",
                ):
                    if skip_reason:
                        topology_results.append(skip_api_resources_and_crd_topology(
                            label, skip_reason,
                        ))
                        continue
                    topology_results.append(
                        compare_api_resources_and_crd_topology(
                            label, bsnap, tsnap,
                        )
                    )
            except (OSError, ValueError, json.JSONDecodeError) as err:
                topology_results.append(skip_api_resources_and_crd_topology(
                    topology, str(err),
                ))
    else:
        for topology in topologies:
            if topology == "osd-gcp" and gcp_skip:
                topology_results.append(skip_api_resources_and_crd_topology(
                    topology, gcp_skip,
                ))
                continue
            baseline_snapshot = find_api_resources_and_crd_snapshot(baseline_minor, topology)
            target_snapshot = find_api_resources_and_crd_snapshot(target_minor, topology)
            for label, bsnap, tsnap, skip_reason in iter_snapshot_role_results(
                topology, baseline_snapshot, target_snapshot, "API Resources and CRD",
                baseline_minor=baseline_minor, target_minor=target_minor,
            ):
                if skip_reason:
                    topology_results.append(skip_api_resources_and_crd_topology(
                        label, skip_reason,
                    ))
                    continue
                topology_results.append(
                    compare_api_resources_and_crd_topology(
                        label, bsnap, tsnap,
                    )
                )

    compared = [result for result in topology_results if result["status"] != "SKIP"]
    skipped = [result for result in topology_results if result["status"] == "SKIP"]
    coverage = topology_coverage_summary(topology_results)

    combined_summary = {
        "new_api_resources": 0,
        "removed_api_resources": 0,
        "api_version_changes": 0,
        "new_crds": 0,
        "removed_crds": 0,
        "crd_version_changes": 0,
        "deprecated_crds": 0,
        "managed_new_crds": 0,
        "managed_deprecated_crds": 0,
        "managed_removed_apis": 0,
        **coverage,
    }
    for result in compared:
        for key in (
            "new_api_resources", "removed_api_resources", "api_version_changes",
            "new_crds", "removed_crds", "crd_version_changes", "deprecated_crds",
            "managed_new_crds", "managed_deprecated_crds", "managed_removed_apis",
        ):
            combined_summary[key] += result["summary"].get(key, 0)

    if not compared:
        validation_result = "SKIP"
        status_message = "; ".join(result["skip_reason"] for result in skipped) or "no snapshots found"
    else:
        validation_result = "PASS"
        changes = total_changes(combined_summary)
        if changes == 0:
            status_message = f"no API/CRD changes ({', '.join(combined_summary['compared_display_names'])})"
        else:
            status_message = (
                f"{changes} change(s) across {', '.join(combined_summary['compared_display_names'])}"
            )

    log_info(f"\nCHECK #{CHECK_NUMBER}: {CHECK_NAME}")
    for result in topology_results:
        print_api_resources_and_crd_topology(result, verbose=args.verbose)

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
            "Informational check. Snapshots come from live HCP, Classic, and OSD GCP clusters. "
            "Each topology is compared to itself. HCP also compares management-cluster "
            "API Resources and CRDs (control plane) when ARTIFACT_DIR/management/ is present. "
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
        log_warning("  Snapshots come from live HCP, Classic, and OSD GCP clusters.")
    else:
        log_success(f"✓ VALIDATION PASSED - {CHECK_NAME} (Informational)")
        log_success("=" * 60)
        log_success(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [PASS - Info]")
        log_success(f"  {status_message}")
        if combined_summary["new_crds"]:
            log_success(f"    • {combined_summary['new_crds']} new CRD(s)")
        if combined_summary["new_api_resources"]:
            log_success(f"    • {combined_summary['new_api_resources']} new API resource(s)")
        if combined_summary["api_version_changes"] or combined_summary["crd_version_changes"]:
            log_success(
                f"    • {combined_summary['api_version_changes'] + combined_summary['crd_version_changes']} version change(s)"
            )
        if combined_summary["deprecated_crds"]:
            log_success(f"    • {combined_summary['deprecated_crds']} newly deprecated CRD version(s)")
        if combined_summary["managed_deprecated_crds"] or combined_summary["managed_removed_apis"]:
            log_warning(
                f"    • managed-service impact: {combined_summary['managed_deprecated_crds']} deprecated CRDs, "
                f"{combined_summary['managed_removed_apis']} removed APIs"
            )
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
