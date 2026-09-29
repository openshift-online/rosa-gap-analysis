from prow_artifacts import (
    ARTIFACT_HTTP_BASES,
    GCS_HTTP_BASE,
    GCSWEB_BASE,
    _load_artifact,
    snapshot_artifact_urls,
)


def test_artifact_http_bases_use_public_bucket():
    assert "test-platform-results-public" in GCS_HTTP_BASE
    assert "test-platform-results-public" in GCSWEB_BASE
    assert GCS_HTTP_BASE.startswith("https://storage.googleapis.com/")
    assert GCSWEB_BASE.startswith("https://gcs.ci.openshift.org/")
    assert ARTIFACT_HTTP_BASES[0] == GCS_HTTP_BASE


def test_snapshot_artifact_urls_prefer_public_gcs():
    urls = snapshot_artifact_urls(
        "periodic-ci-openshift-online-rosa-e2e-main-periodics-rosa-hcp-e2e-staging-stable-4-22",
        "2104421402961514496",
        "rosa-hcp-e2e-staging-stable-4-22",
        "metadata.json",
        "rosa-gap-analysis-api-resources-and-crd",
    )
    assert urls[0].startswith(GCS_HTTP_BASE)
    assert "test-platform-results-public" in urls[0]
    assert "storage.googleapis.com/test-platform-results/" not in "".join(urls)
    assert "gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com" not in "".join(urls)


def test_load_artifact_uses_first_successful_public_url():
    payload, url = _load_artifact(
        "job",
        "1",
        "test",
        "metadata.json",
        "step",
        lambda fetched: {"ok": True} if "test-platform-results-public" in fetched else None,
    )
    assert payload == {"ok": True}
    assert url.startswith(GCS_HTTP_BASE)
