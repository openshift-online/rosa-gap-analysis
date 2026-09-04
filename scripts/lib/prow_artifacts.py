#!/usr/bin/env python3
"""Fetch Check #9, #10, #11 snapshots, Check #12 e2e JUnit, and Check #13 upgrade jobs.

Check #9  API Resources and CRD Diff Validation
Check #10 Critical Alerts Diff Validation
Check #11 Cluster Install and Delete Validation
Check #12 Target E2E Validation and alert monitoring (junit-rosa-e2e.xml)
Check #13 Upgrade Validation from Y-1 to Y with E2E Tests (rosa-e2e upgrade periodics)

GCS artifact folder names (ci-operator `as:`) live in
API_RESOURCES_AND_CRD_STEP, CRITICAL_ALERTS_STEP, CLUSTER_INSTALL_STEP,
and E2E_TEST_STEP and must match CI.
"""

import json
import re
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError

from common import fetch_url, is_version_5x, log_info, log_warning
from openshift_releases import extract_minor_version, fetch_sippy_ga_dates, is_ga_minor_version

PROW_HISTORY_URL = "https://prow.ci.openshift.org/job-history/gs/test-platform-results/logs"
GCS_HTTP_BASE = "https://storage.googleapis.com/test-platform-results/logs"
GCSWEB_BASE = "https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/test-platform-results/logs"
JOB_PREFIX = "periodic-ci-openshift-online-rosa-e2e-main-periodics"
UPGRADE_JOB_PREFIX = "periodic-ci-openshift-online-rosa-e2e-main-upgrade"
UPGRADE_Y_MINUS_1 = "y-minus-1"
UPGRADE_CLASSIC_STEP = "rosa-cluster-upgrade-cluster"
UPGRADE_HCP_STEP = "rosa-cluster-upgrade-hcp"
UPGRADE_OSD_GCP_STEP = "osd-ccs-cluster-upgrade"
UPGRADE_MACHINEPOOL_STEP = "rosa-cluster-upgrade-machinepool"
UPGRADE_METRICS_FILE = "upgrade-metrics.json"
WAIT_READY_OPERATORS_STEP = "rosa-cluster-wait-ready-operators"
OSD_GCP_WAIT_READY_STEP = "osd-ccs-cluster-operators-wait-ready"
PRE_UPGRADE_CO_JSON = "pre-upgrade-clusteroperators.json"
PRE_UPGRADE_NODES_JSON = "pre-upgrade-nodes.json"
PRE_UPGRADE_META_JSON = "pre-upgrade-metadata.json"
PRE_UPGRADE_CO_TXT = "pre-upgrade-clusteroperators.txt"
PRE_UPGRADE_NODES_TXT = "pre-upgrade-nodes.txt"
CLUSTER_INSTALL_CO_TXT = "clusteroperators.txt"
CLUSTER_INSTALL_NODES_TXT = "nodes.txt"
CLUSTER_INSTALL_REPORT_TXT = "gap-analysis-cluster-install-report.txt"

# CI snapshot step `as:` names (GCS artifact folders). Keep in sync with the
# snapshot refs in the OpenShift release step-registry.
API_RESOURCES_AND_CRD_STEP = "rosa-gap-analysis-api-resources-and-crd"
API_RESOURCES_AND_CRD_FILES = ("metadata.json", "api-resources.json", "crds.json")
CRITICAL_ALERTS_STEP = "rosa-gap-analysis-critical-alerts"
CRITICAL_ALERTS_FILES = ("metadata.json", "alerts.json")
CLUSTER_INSTALL_STEP = "rosa-gap-analysis-cluster-install-delete-metrics"
CLUSTER_INSTALL_FILES = ("metadata.json", "clusteroperators.json", "nodes.json")
E2E_TEST_STEP = "rosa-e2e-test"
E2E_JUNIT_FILE = "junit-rosa-e2e.xml"
MANAGEMENT_SUBDIR = "management"

# Core rosa-e2e periodics target OCM staging. Job names are:
#   rosa-hcp-e2e-staging-{channel}-{minor}
#   rosa-classic-sts-e2e-staging-{channel}-{minor}
#   osd-gcp-e2e-staging-{channel}-{minor}
# Channel is chosen from GA status, not a hardcoded per-minor map:
#   GA      → stable
#   pre-GA  → candidate if that job has a snapshot, else nightly
OCM_ENV = "staging"
GA_SNAPSHOT_CHANNELS = ("stable",)
PRE_GA_SNAPSHOT_CHANNELS = ("candidate", "nightly")
_GA_DATES_CACHE = None

USABLE_RESULTS = {"SUCCESS", "FAILURE", "ERROR"}


def minor_to_job_suffix(minor):
    """Convert '4.21' to '4-21'."""
    return minor.replace(".", "-")


def _ga_dates(ga_dates=None):
    """Return Sippy GA dates, cached for the process."""
    global _GA_DATES_CACHE
    if ga_dates is not None:
        return ga_dates
    if _GA_DATES_CACHE is None:
        _GA_DATES_CACHE = fetch_sippy_ga_dates()
    return _GA_DATES_CACHE


def snapshot_channels(minor, ga_dates=None):
    """Prow job channel search order for a minor version.

    GA minors use the stable periodic. Pre-GA minors try candidate first,
    then nightly if that job has no snapshot yet.
    """
    if is_ga_minor_version(minor, ga_dates=_ga_dates(ga_dates)):
        return list(GA_SNAPSHOT_CHANNELS)
    return list(PRE_GA_SNAPSHOT_CHANNELS)


def test_name(minor, topology, channel=None, ga_dates=None):
    """Return the ci-operator test name (also the artifacts subdirectory)."""
    if not channel:
        channels = snapshot_channels(minor, ga_dates=ga_dates)
        channel = channels[0] if channels else None
    if not channel:
        return None
    suffix = minor_to_job_suffix(minor)
    if topology == "hcp":
        return f"rosa-hcp-e2e-{OCM_ENV}-{channel}-{suffix}"
    if topology == "classic":
        return f"rosa-classic-sts-e2e-{OCM_ENV}-{channel}-{suffix}"
    if topology == "osd-gcp":
        return f"osd-gcp-e2e-{OCM_ENV}-{channel}-{suffix}"
    raise ValueError(f"Unsupported topology: {topology}")


def prow_job_name(minor, topology, channel=None, ga_dates=None):
    """Return the full Prow periodic job name."""
    as_name = test_name(minor, topology, channel=channel, ga_dates=ga_dates)
    if not as_name:
        return None
    return f"{JOB_PREFIX}-{as_name}"


def topology_pair_label(baseline_topology, target_topology):
    """Human-readable comparison label (e.g. 'hcp' or 'classic')."""
    if baseline_topology == target_topology:
        return baseline_topology
    return f"{baseline_topology}→{target_topology}"


def topology_display_name(label):
    """Report heading for a comparison pair."""
    names = {
        "hcp": "HCP hosted (data plane)",
        "hcp-management": "HCP management (control plane)",
        "classic": "Classic",
        "osd-gcp": "OSD GCP",
    }
    return names.get(label, label)


def result_display_name(result):
    """Display name from a topology result dict."""
    return result.get("display_name") or topology_display_name(result.get("topology") or "")


def topology_coverage_summary(results, include_failed=False):
    """Compared/skipped topology ids and display names for reports."""
    compared = [item for item in results if item.get("status") != "SKIP"]
    skipped = [item for item in results if item.get("status") == "SKIP"]
    summary = {
        "compared_topologies": [item["topology"] for item in compared],
        "skipped_topologies": [item["topology"] for item in skipped],
        "compared_display_names": [result_display_name(item) for item in compared],
        "skipped_display_names": [result_display_name(item) for item in skipped],
    }
    if include_failed:
        failed = [item for item in results if item.get("status") == "FAIL"]
        summary["failed_topologies"] = [item["topology"] for item in failed]
        summary["failed_display_names"] = [result_display_name(item) for item in failed]
    return summary


DEFAULT_TOPOLOGIES = ("hcp", "classic", "osd-gcp")
UPGRADE_DEFAULT_TOPOLOGIES = ("hcp", "classic", "osd-gcp")
TOPOLOGY_CHOICES = DEFAULT_TOPOLOGIES
TOPOLOGY_HELP = (
    "Topology to compare (repeatable). Default: hcp, classic, and osd-gcp. "
    "Each topology is compared to itself. OSD GCP is skipped for OpenShift 5.x "
    "(AWS/STS-only). HCP also compares management-cluster snapshots when present."
)
UPGRADE_TOPOLOGY_HELP = (
    "Topology to validate (repeatable). Default: hcp, classic, and osd-gcp. "
    "Missing upgrade JUnit is SKIP. OSD GCP looks for "
    "osd-gcp-upgrade-staging-y-minus-1."
)


def osd_gcp_skip_reason(*minors):
    """Return a SKIP reason when OSD GCP does not apply to these minors.

    OpenShift 5.x is AWS/STS-only; OSD GCP has no 5.x jobs and no HCP variant.
    """
    fives = [minor for minor in minors if minor and is_version_5x(minor)]
    if not fives:
        return None
    shown = ", ".join(dict.fromkeys(fives))
    return (
        f"OSD GCP is not applicable for OpenShift {shown} "
        "(5.x is AWS/STS-only)"
    )


class _ArtifactMissing(Exception):
    """Snapshot object is not in GCS; mirrors will not have it either."""


def fetch_json_url(url):
    """Fetch JSON from URL. Returns None on HTML or retryable errors.

    Raises _ArtifactMissing on HTTP 404 so callers skip the gcsweb mirror
    for that object, then try the next artifact path.
    """
    try:
        data = fetch_url(url, timeout=45)
        stripped = data.lstrip() if data else b""
        if not stripped or stripped[:1] not in (b"{", b"["):
            return None
        return json.loads(data)
    except HTTPError as err:
        if err.code == 404:
            raise _ArtifactMissing from err
        log_warning(f"HTTP {err.code} fetching {url}")
        return None
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as err:
        log_warning(f"Failed to fetch {url}: {err}")
        return None


def fetch_text_url(url, xml=False):
    """Fetch a text/XML artifact. Returns None on HTML or retryable errors.

    Raises _ArtifactMissing on HTTP 404 so callers skip the gcsweb mirror
    for that object, then try the next artifact path.
    """
    try:
        data = fetch_url(url, timeout=45)
        stripped = data.lstrip() if data else b""
        if not stripped:
            return None
        if xml:
            low = stripped.lower()
            if stripped[:1] != b"<" or low.startswith(b"<!doctype") or low.startswith(b"<html"):
                return None
        return data.decode("utf-8", errors="replace")
    except HTTPError as err:
        if err.code == 404:
            raise _ArtifactMissing from err
        log_warning(f"HTTP {err.code} fetching {url}")
        return None
    except (URLError, TimeoutError, ValueError) as err:
        log_warning(f"Failed to fetch {url}: {err}")
        return None


def list_job_builds(job_name, limit=20):
    """Parse Prow job-history HTML for recent builds (newest first)."""
    url = f"{PROW_HISTORY_URL}/{job_name}"
    try:
        html = fetch_url(url, timeout=45).decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError) as err:
        log_warning(f"Failed to list job history for {job_name}: {err}")
        return []

    match = re.search(r"var allBuilds = (\[.*?\]);", html, re.DOTALL)
    if not match:
        log_warning(f"No build history found for {job_name}")
        return []

    try:
        builds = json.loads(match.group(1))
    except json.JSONDecodeError as err:
        log_warning(f"Failed to parse job history for {job_name}: {err}")
        return []

    return builds[:limit]


def snapshot_label(step_name):
    """Human-readable snapshot name for logs (not the GCS folder)."""
    if step_name == API_RESOURCES_AND_CRD_STEP:
        return "API Resources and CRD"
    if step_name == CRITICAL_ALERTS_STEP:
        return "Critical Alerts"
    if step_name == CLUSTER_INSTALL_STEP:
        return "Cluster Install"
    if step_name == E2E_TEST_STEP:
        return "Target E2E JUnit"
    return step_name


def _artifact_rel_paths(job_name, build_id, as_name, filename, step_name):
    """Nested ci-operator path first, then the step root beside build-log.txt."""
    return (
        f"{job_name}/{build_id}/artifacts/{as_name}/{step_name}/artifacts/{filename}",
        f"{job_name}/{build_id}/artifacts/{as_name}/{step_name}/{filename}",
    )


def snapshot_artifact_urls(job_name, build_id, as_name, filename, step_name):
    """Return candidate URLs for a snapshot/JUnit file (GCS then gcsweb).

    ci-operator uploads $ARTIFACT_DIR under
    artifacts/<test>/<step>/artifacts/<file>. Also try the step root for
    files that land beside build-log.txt.
    """
    urls = []
    for rel in _artifact_rel_paths(job_name, build_id, as_name, filename, step_name):
        urls.append(f"{GCS_HTTP_BASE}/{rel}")
        urls.append(f"{GCSWEB_BASE}/{rel}")
    return urls


def _load_artifact(job_name, build_id, as_name, filename, step_name, fetcher):
    """Fetch one artifact. Try nested then step-root path.

    A GCS 404 means the gcsweb mirror of the same path cannot have the object,
    so skip that mirror. Still try the other artifact path.
    """
    for rel in _artifact_rel_paths(job_name, build_id, as_name, filename, step_name):
        gcs_url = f"{GCS_HTTP_BASE}/{rel}"
        try:
            payload = fetcher(gcs_url)
        except _ArtifactMissing:
            continue
        if payload is not None:
            return payload, gcs_url
        gcsweb_url = f"{GCSWEB_BASE}/{rel}"
        try:
            payload = fetcher(gcsweb_url)
        except _ArtifactMissing:
            continue
        if payload is not None:
            return payload, gcsweb_url
    return None, None


def load_snapshot_from_build(job_name, build_id, as_name, step_name, files, include_management=False):
    """Load a snapshot file set from one Prow build. None if incomplete."""
    snapshot = {}
    used_url = None
    for filename in files:
        payload, fetched_url = _load_artifact(
            job_name, build_id, as_name, filename, step_name, fetch_json_url,
        )
        if payload is None:
            return None
        snapshot[filename] = payload
        used_url = fetched_url
    snapshot["source"] = {
        "job_name": job_name,
        "build_id": str(build_id),
        "test_name": as_name,
        "gcs_url": used_url or snapshot_artifact_urls(job_name, build_id, as_name, files[0], step_name)[0],
        "cluster_role": (snapshot.get("metadata.json") or {}).get("cluster_role") or "",
    }
    if include_management:
        management = _load_management_files(job_name, build_id, as_name, step_name, files)
        if management:
            snapshot["management"] = management
    return snapshot


def _load_management_files(job_name, build_id, as_name, step_name, files):
    """Load HCP management-cluster files from ARTIFACT_DIR/management/. None if incomplete."""
    snapshot = {}
    used_url = None
    for filename in files:
        payload, fetched_url = _load_artifact(
            job_name, build_id, as_name, f"{MANAGEMENT_SUBDIR}/{filename}", step_name,
            fetch_json_url,
        )
        if payload is None:
            return None
        snapshot[filename] = payload
        used_url = fetched_url
    snapshot["source"] = {
        "job_name": job_name,
        "build_id": str(build_id),
        "test_name": as_name,
        "gcs_url": used_url or "",
        "cluster_role": (snapshot.get("metadata.json") or {}).get("cluster_role") or "management",
    }
    return snapshot


def find_snapshot(minor, topology, step_name, files, build_limit=20, ga_dates=None):
    """
    Find the newest snapshot for a minor version + topology + snapshot step.

    Prow channel: GA → stable; pre-GA → candidate, then nightly.
    Accepts snapshots from SUCCESS or FAILURE jobs because snapshot steps run
    in post (after e2e-test, before deprovision). Missing jobs are SKIP.
    """
    label = snapshot_label(step_name)
    channels = snapshot_channels(minor, ga_dates=ga_dates)
    log_info(
        f"{minor} Prow channel search for {label}: {', '.join(channels)} "
        f"({'GA → stable' if channels == list(GA_SNAPSHOT_CHANNELS) else 'pre-GA → candidate, else nightly'})"
    )
    for channel in channels:
        as_name = test_name(minor, topology, channel=channel)
        job_name = prow_job_name(minor, topology, channel=channel)
        if not as_name or not job_name:
            continue
        log_info(f"Looking for {topology} {minor} {label} snapshot in {job_name}")
        builds = list_job_builds(job_name, limit=build_limit)
        for build in builds:
            result = str(build.get("Result", "")).upper()
            build_id = build.get("ID")
            if not build_id or result not in USABLE_RESULTS:
                continue
            snapshot = load_snapshot_from_build(
                job_name, build_id, as_name, step_name, files,
                include_management=(topology == "hcp"),
            )
            if snapshot:
                meta = snapshot.get("metadata.json") or {}
                log_info(
                    f"Found {topology} {label}: job={job_name} build={build_id} "
                    f"cluster_version={meta.get('cluster_version', 'unknown')} result={result}"
                )
                if snapshot.get("management"):
                    log_info(f"  includes management-cluster {label} snapshot")
                return snapshot
        log_info(f"No {label} artifacts in recent runs of {job_name}")
    return None


def load_snapshot_from_dir(path, files, include_management=True):
    """Load a snapshot from a local directory."""
    directory = Path(path)
    snapshot = {}
    for filename in files:
        file_path = directory / filename
        if not file_path.is_file():
            raise FileNotFoundError(f"Missing {file_path}")
        with file_path.open("r", encoding="utf-8") as handle:
            snapshot[filename] = json.load(handle)
    snapshot["source"] = {
        "job_name": "local",
        "build_id": "",
        "test_name": "local",
        "gcs_url": str(directory),
        "cluster_role": (snapshot.get("metadata.json") or {}).get("cluster_role") or "",
    }
    if include_management:
        management_dir = directory / MANAGEMENT_SUBDIR
        if all((management_dir / filename).is_file() for filename in files):
            snapshot["management"] = load_snapshot_from_dir(
                management_dir, files, include_management=False
            )
            snapshot["management"]["source"]["cluster_role"] = (
                (snapshot["management"].get("metadata.json") or {}).get("cluster_role")
                or "management"
            )
    return snapshot


def snapshot_role_pairs(topology, baseline_snapshot, target_snapshot):
    """Yield (label, baseline, target) for the primary cluster, plus HCP management when present.

    Root artifacts are the Classic cluster, OSD GCP cluster, or the HCP hosted/guest data plane.
    HCP management-cluster artifacts are nested under snapshot['management'].
    Classic and OSD GCP never compare a management pair, even if a management/ dir exists.
    """
    pairs = [(topology, baseline_snapshot, target_snapshot)]
    if topology != "hcp":
        return pairs
    baseline_management = (baseline_snapshot or {}).get("management")
    target_management = (target_snapshot or {}).get("management")
    if baseline_management or target_management:
        pairs.append((f"{topology}-management", baseline_management, target_management))
    return pairs


def iter_snapshot_role_results(
    topology, baseline_snapshot, target_snapshot, label_text,
    baseline_minor="", target_minor="",
):
    """Yield (label, baseline, target, skip_reason) for hosted and optional HCP management."""
    for label, baseline, target in snapshot_role_pairs(
        topology, baseline_snapshot, target_snapshot,
    ):
        if not baseline and not target:
            if baseline_minor or target_minor:
                reason = (
                    f"no {label_text} snapshots found for "
                    f"{label} {baseline_minor} or {label} {target_minor}"
                )
            else:
                reason = f"no {label_text} snapshots found for {label}"
            yield label, None, None, reason
            continue
        if not baseline:
            suffix = f" {baseline_minor}" if baseline_minor else ""
            yield label, None, None, f"no baseline snapshot found for {label}{suffix}"
            continue
        if not target:
            suffix = f" {target_minor}" if target_minor else ""
            yield label, None, None, f"no target snapshot found for {label}{suffix}"
            continue
        yield label, baseline, target, None


def find_api_resources_and_crd_snapshot(minor, topology, build_limit=20):
    """Find the newest API Resources and CRD snapshot."""
    return find_snapshot(
        minor, topology,
        step_name=API_RESOURCES_AND_CRD_STEP,
        files=API_RESOURCES_AND_CRD_FILES,
        build_limit=build_limit,
    )


def load_api_resources_and_crd_snapshot(path):
    """Load an API Resources and CRD snapshot from a local directory."""
    return load_snapshot_from_dir(path, API_RESOURCES_AND_CRD_FILES)


def find_critical_alerts_snapshot(minor, topology, build_limit=20):
    """Find the newest Critical Alerts snapshot."""
    return find_snapshot(
        minor, topology,
        step_name=CRITICAL_ALERTS_STEP,
        files=CRITICAL_ALERTS_FILES,
        build_limit=build_limit,
    )


def load_critical_alerts_snapshot(path):
    """Load a Critical Alerts snapshot from a local directory."""
    return load_snapshot_from_dir(path, CRITICAL_ALERTS_FILES)


def find_cluster_install_snapshot(minor, topology, build_limit=20):
    """Find the newest Cluster Install snapshot."""
    return find_snapshot(
        minor, topology,
        step_name=CLUSTER_INSTALL_STEP,
        files=CLUSTER_INSTALL_FILES,
        build_limit=build_limit,
    )


def load_cluster_install_snapshot(path):
    """Load a Cluster Install snapshot from a local directory."""
    return load_snapshot_from_dir(path, CLUSTER_INSTALL_FILES)


def load_e2e_junit_from_build(job_name, build_id, as_name, job_result):
    """Load junit-rosa-e2e.xml from one Prow build. None if missing."""
    payload, used_url = _load_artifact(
        job_name, build_id, as_name, E2E_JUNIT_FILE, E2E_TEST_STEP,
        lambda url: fetch_text_url(url, xml=True),
    )
    if payload is None:
        return None
    return {
        E2E_JUNIT_FILE: payload,
        "source": {
            "job_name": job_name,
            "build_id": str(build_id),
            "test_name": as_name,
            "job_result": job_result,
            "gcs_url": used_url or snapshot_artifact_urls(
                job_name, build_id, as_name, E2E_JUNIT_FILE, E2E_TEST_STEP,
            )[0],
        },
    }


def find_e2e_junit(minor, topology, build_limit=20, ga_dates=None):
    """Find the newest rosa-e2e JUnit report for a minor version + topology."""
    label = snapshot_label(E2E_TEST_STEP)
    channels = snapshot_channels(minor, ga_dates=ga_dates)
    log_info(
        f"{minor} Prow channel search for {label}: {', '.join(channels)} "
        f"({'GA → stable' if channels == list(GA_SNAPSHOT_CHANNELS) else 'pre-GA → candidate, else nightly'})"
    )
    for channel in channels:
        as_name = test_name(minor, topology, channel=channel)
        job_name = prow_job_name(minor, topology, channel=channel)
        if not as_name or not job_name:
            continue
        log_info(f"Looking for {topology} {minor} {label} in {job_name}")
        builds = list_job_builds(job_name, limit=build_limit)
        for build in builds:
            result = str(build.get("Result", "")).upper()
            build_id = build.get("ID")
            if not build_id or result not in USABLE_RESULTS:
                continue
            snapshot = load_e2e_junit_from_build(job_name, build_id, as_name, result)
            if snapshot:
                log_info(
                    f"Found {topology} {label}: job={job_name} build={build_id} result={result}"
                )
                return snapshot
        log_info(f"No {label} artifacts in recent runs of {job_name}")
    return None


def load_e2e_junit_from_path(path):
    """Load junit-rosa-e2e.xml from a file or directory."""
    candidate = Path(path)
    if candidate.is_dir():
        candidate = candidate / E2E_JUNIT_FILE
    if not candidate.is_file():
        raise FileNotFoundError(f"Missing {candidate}")
    return {
        E2E_JUNIT_FILE: candidate.read_text(encoding="utf-8", errors="replace"),
        "source": {
            "job_name": "local",
            "build_id": "",
            "test_name": "local",
            "job_result": "",
            "gcs_url": str(candidate),
        },
    }


def upgrade_test_name(topology):
    """ci-operator test name for the rosa-e2e Y-1 → Y upgrade periodic."""
    if topology == "hcp":
        return f"rosa-hcp-upgrade-{OCM_ENV}-{UPGRADE_Y_MINUS_1}"
    if topology == "classic":
        return f"rosa-classic-sts-upgrade-{OCM_ENV}-{UPGRADE_Y_MINUS_1}"
    if topology == "osd-gcp":
        return f"osd-gcp-upgrade-{OCM_ENV}-{UPGRADE_Y_MINUS_1}"
    raise ValueError(f"Unsupported topology: {topology}")


def upgrade_prow_job_name(topology):
    """Full Prow job name for the rosa-e2e Y-1 → Y upgrade periodic."""
    as_name = upgrade_test_name(topology)
    if not as_name:
        return None
    return f"{UPGRADE_JOB_PREFIX}-{as_name}"


def upgrade_step_candidates(topology):
    """Upgrade-step `as:` names to try for duration and pre-upgrade artifacts."""
    if topology == "hcp":
        return (UPGRADE_HCP_STEP,)
    if topology == "osd-gcp":
        return (UPGRADE_OSD_GCP_STEP, UPGRADE_CLASSIC_STEP)
    return (UPGRADE_CLASSIC_STEP,)


def upgrade_step_name(topology):
    """Primary upgrade-step `as:` name used for optional duration artifacts."""
    return upgrade_step_candidates(topology)[0]


def wait_ready_step_name(topology):
    """Pre-upgrade operators-ready step used for duration fallback."""
    if topology == "osd-gcp":
        return OSD_GCP_WAIT_READY_STEP
    return WAIT_READY_OPERATORS_STEP


def parse_clusteroperators_txt(text):
    """Parse `oc get co -o wide` into the Check #11 clusteroperators.json shape."""
    items = []
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return {"items": []}
    if not lines[0].lower().startswith("name"):
        return {"items": []}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        name, version, available, progressing, degraded = parts[:5]
        items.append({
            "name": name,
            "version": version,
            "available": available,
            "progressing": progressing,
            "degraded": degraded,
        })
    return {"items": items}


def parse_nodes_txt(text):
    """Parse `oc get nodes -o wide` into the Check #11 nodes.json shape."""
    items = []
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return {"items": []}
    if not lines[0].lower().startswith("name"):
        return {"items": []}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        name, status = parts[0], parts[1]
        items.append({
            "name": name,
            "ready": "True" if status == "Ready" else "False",
        })
    return {"items": items}


def parse_install_report_overall(text):
    """Read Overall Status from gap-analysis-cluster-install-report.txt."""
    for line in (text or "").splitlines():
        if "Overall Status:" in line:
            return line.split(":", 1)[1].strip()
    return ""


def format_duration_seconds(seconds):
    """Human-readable duration for reports."""
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s ({total}s)"
    if minutes:
        return f"{minutes}m {secs}s ({total}s)"
    return f"{total}s"


def _minor_from_value(value):
    if not value:
        return ""
    try:
        return extract_minor_version(str(value))
    except (TypeError, ValueError, AttributeError):
        return ""


def snapshot_post_minor(snapshot):
    """Post-upgrade minor from cluster_version or ClusterOperator VERSION column.

    Do not use metadata.openshift_version as post-upgrade: that field is the
    provisioned Y-1 request on JSON snapshots.
    """
    meta = (snapshot or {}).get("metadata.json") or {}
    minor = _minor_from_value(meta.get("cluster_version"))
    if minor:
        return minor
    items = ((snapshot or {}).get("clusteroperators.json") or {}).get("items") or []
    versions = [_minor_from_value(item.get("version")) for item in items]
    versions = [ver for ver in versions if ver]
    if versions:
        return Counter(versions).most_common(1)[0][0]
    return ""


def _txt_health_snapshot(co_text, nodes_text, report_text, source):
    operators = parse_clusteroperators_txt(co_text)
    nodes = parse_nodes_txt(nodes_text or "")
    versions = [item.get("version") for item in operators["items"] if item.get("version")]
    cluster_version = Counter(versions).most_common(1)[0][0] if versions else ""
    return {
        "clusteroperators.json": operators,
        "nodes.json": nodes,
        "metadata.json": {
            "cluster_version": cluster_version,
            "overall_status": parse_install_report_overall(report_text or ""),
            "node_count": len(nodes["items"]),
        },
        "source": source,
    }


def load_upgrade_post_health(job_name, build_id, as_name):
    """JSON snapshot if present; otherwise oc-get txt dumps from this job."""
    snapshot = load_snapshot_from_build(
        job_name, build_id, as_name, CLUSTER_INSTALL_STEP, CLUSTER_INSTALL_FILES,
        include_management=False,
    )
    if snapshot:
        return snapshot
    for prefix in ("", "diagnostics/"):
        co_text, co_url = _load_artifact(
            job_name, build_id, as_name, f"{prefix}{CLUSTER_INSTALL_CO_TXT}",
            CLUSTER_INSTALL_STEP, fetch_text_url,
        )
        if not co_text:
            continue
        if not parse_clusteroperators_txt(co_text).get("items"):
            continue
        nodes_text, _ = _load_artifact(
            job_name, build_id, as_name, f"{prefix}{CLUSTER_INSTALL_NODES_TXT}",
            CLUSTER_INSTALL_STEP, fetch_text_url,
        )
        report_text, _ = _load_artifact(
            job_name, build_id, as_name, f"{prefix}{CLUSTER_INSTALL_REPORT_TXT}",
            CLUSTER_INSTALL_STEP, fetch_text_url,
        )
        return _txt_health_snapshot(
            co_text, nodes_text, report_text,
            {
                "job_name": job_name,
                "build_id": str(build_id),
                "test_name": as_name,
                "gcs_url": co_url or "",
            },
        )
    return None


def load_pre_upgrade_snapshot(job_name, build_id, as_name, topology):
    """Pre-upgrade COs from the upgrade step (JSON preferred, txt fallback)."""
    for step in upgrade_step_candidates(topology):
        payload, url = _load_artifact(
            job_name, build_id, as_name, PRE_UPGRADE_CO_JSON, step, fetch_json_url,
        )
        if payload:
            nodes, _ = _load_artifact(
                job_name, build_id, as_name, PRE_UPGRADE_NODES_JSON, step, fetch_json_url,
            )
            meta, _ = _load_artifact(
                job_name, build_id, as_name, PRE_UPGRADE_META_JSON, step, fetch_json_url,
            )
            return {
                "clusteroperators.json": payload,
                "nodes.json": nodes or {"items": []},
                "metadata.json": meta or {},
                "source": {
                    "job_name": job_name,
                    "build_id": str(build_id),
                    "test_name": as_name,
                    "gcs_url": url or "",
                },
            }
        co_text, url = _load_artifact(
            job_name, build_id, as_name, PRE_UPGRADE_CO_TXT, step, fetch_text_url,
        )
        if not co_text:
            continue
        nodes_text, _ = _load_artifact(
            job_name, build_id, as_name, PRE_UPGRADE_NODES_TXT, step, fetch_text_url,
        )
        return _txt_health_snapshot(
            co_text, nodes_text, "",
            {
                "job_name": job_name,
                "build_id": str(build_id),
                "test_name": as_name,
                "gcs_url": url or "",
            },
        )
    return None


def _finished_epoch(job_name, build_id, as_name, step_name):
    payload, url = _load_artifact(
        job_name, build_id, as_name, "finished.json", step_name, fetch_json_url,
    )
    if not payload or payload.get("timestamp") is None:
        return None, url or ""
    try:
        return int(payload["timestamp"]), url or ""
    except (TypeError, ValueError):
        return None, url or ""


def load_upgrade_duration(job_name, build_id, as_name, topology):
    """Prefer upgrade-metrics.json; else upgrade finished minus operators-ready finished."""
    skip = {
        "status": "SKIP",
        "skip_reason": (
            "upgrade duration not available "
            "(no upgrade-metrics.json or finished.json timestamps)"
        ),
        "duration": "",
        "duration_seconds": None,
        "source_url": "",
        "from_version": "",
        "to_version": "",
    }
    for step in upgrade_step_candidates(topology):
        metrics, metrics_url = _load_artifact(
            job_name, build_id, as_name, UPGRADE_METRICS_FILE, step, fetch_json_url,
        )
        if metrics and metrics.get("duration_seconds") is not None:
            seconds = metrics.get("duration_seconds")
            return {
                "status": "INFO",
                "skip_reason": "",
                "duration": format_duration_seconds(seconds),
                "duration_seconds": seconds,
                "source_url": metrics_url or "",
                "from_version": metrics.get("from_version") or "",
                "to_version": metrics.get("to_version") or "",
            }
        upgrade_ts, upgrade_url = _finished_epoch(job_name, build_id, as_name, step)
        if upgrade_ts is not None:
            break
    else:
        upgrade_ts, upgrade_url = None, ""
    if topology == "hcp":
        mp_ts, mp_url = _finished_epoch(
            job_name, build_id, as_name, UPGRADE_MACHINEPOOL_STEP,
        )
        if mp_ts is not None and (upgrade_ts is None or mp_ts >= upgrade_ts):
            upgrade_ts, upgrade_url = mp_ts, mp_url
    ready_ts, _ = _finished_epoch(
        job_name, build_id, as_name, wait_ready_step_name(topology),
    )
    if upgrade_ts is None or ready_ts is None or upgrade_ts < ready_ts:
        return skip
    seconds = upgrade_ts - ready_ts
    return {
        "status": "INFO",
        "skip_reason": "",
        "duration": format_duration_seconds(seconds),
        "duration_seconds": seconds,
        "source_url": upgrade_url,
        "from_version": "",
        "to_version": "",
    }


def find_upgrade_validation(target_minor, topology, build_limit=20):
    """Find the newest Y-1 → Y upgrade job artifacts for a topology.

    Requires post-upgrade JUnit and a post-upgrade minor that matches target.
    Post-upgrade COs come from JSON snapshots or oc-get txt dumps. Duration
    comes from upgrade-metrics.json or finished.json timestamps. Pre-upgrade
    COs are used when the upgrade step published them.
    """
    as_name = upgrade_test_name(topology)
    job_name = upgrade_prow_job_name(topology)
    if not as_name or not job_name:
        return None

    log_info(f"Looking for {topology} Y-1→Y upgrade validation in {job_name}")
    builds = list_job_builds(job_name, limit=build_limit)
    for build in builds:
        result = str(build.get("Result", "")).upper()
        build_id = build.get("ID")
        if not build_id or result not in USABLE_RESULTS:
            continue

        junit = load_e2e_junit_from_build(job_name, build_id, as_name, result)
        if not junit:
            continue

        post_install = load_upgrade_post_health(job_name, build_id, as_name)
        post_minor = snapshot_post_minor(post_install)
        if post_minor != target_minor:
            log_info(
                f"Skipping {job_name}/{build_id}: post-upgrade version "
                f"{post_minor or 'unknown'} does not match target {target_minor}"
            )
            continue

        pre_install = load_pre_upgrade_snapshot(job_name, build_id, as_name, topology)
        duration = load_upgrade_duration(job_name, build_id, as_name, topology)
        log_info(
            f"Found {topology} upgrade validation: job={job_name} "
            f"build={build_id} result={result} post={post_minor}"
        )
        return {
            "junit": junit,
            "post_install": post_install,
            "pre_install": pre_install,
            "duration": duration,
            "job_result": result,
            "source": junit.get("source") or {},
        }

    log_info(f"No Y-1→Y upgrade JUnit matching {target_minor} in recent runs of {job_name}")
    return None

