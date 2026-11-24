"""Offline fixtures for the Sippy releases API.

Mirrors the shape of https://sippy.dptools.openshift.org/api/releases, which
serves every product Sippy tracks from one endpoint: the deprecated `ga_dates`
map holds an entry for each release that has a GA date, whatever its product,
and `release_attrs` names that product. The live payload carries `logging-6.6`
(product "OCP Logging") and OKD streams alongside the OCP minors, which is why
the GA resolver cannot treat `ga_dates` as an OpenShift-only map.

Trimmed to the entries the resolver reasons about; the real response lists
every OCP minor back to 3.11 plus Quay, ARO, ROSA and other products.
"""

# One release per product shape the resolver must cope with:
#   - OCP minors that have GA'd (4.19, 5.0) — the only candidates
#   - an OCP minor that has not GA'd yet (5.1): absent from ga_dates
#   - OCP Logging (logging-6.6): a GA'd release whose key is not a version
#   - OKD (5.0-okd): a non-OCP product sharing an OCP version prefix
MIXED_PRODUCT_RELEASES = {
    "releases": ["5.1", "5.0", "5.0-okd", "logging-6.6", "4.19"],
    "ga_dates": {
        "4.19": "2025-06-17",
        "5.0": "2026-11-03",
        "logging-6.6": "2026-07-14",
    },
    "release_attrs": {
        "4.19": {
            "name": "4.19",
            "ga": "2025-06-17",
            "development_start": "2024-11-25",
            "previous_release": "4.18",
            "product": "OCP",
        },
        "5.0": {
            "name": "5.0",
            "ga": "2026-11-03",
            "development_start": "2026-04-13",
            "previous_release": "4.22",
            "product": "OCP",
        },
        "5.1": {
            "name": "5.1",
            "development_start": "2026-08-14",
            "previous_release": "5.0",
            "product": "OCP",
        },
        "5.0-okd": {
            "name": "5.0-okd",
            "development_start": "2026-04-13",
            "previous_release": "",
            "product": "OKD",
        },
        "logging-6.6": {
            "name": "logging-6.6",
            "ga": "2026-07-14",
            "development_start": "2026-04-01",
            "previous_release": "",
            "product": "OCP Logging",
        },
    },
}

# The latest GA'd OCP release in MIXED_PRODUCT_RELEASES. logging-6.6 GA'd later
# in wall-clock terms and 5.1 is a newer OCP minor, so picking either would be
# wrong for a different reason.
MIXED_PRODUCT_LATEST_GA = "5.0"

# Every GA'd release belongs to another product: there is no OCP version to
# resolve, and the resolver must say so rather than hand back logging-6.6.
NO_OCP_GA_RELEASES = {
    "releases": ["logging-6.6", "quay-3.18"],
    "ga_dates": {
        "logging-6.6": "2026-07-14",
        "quay-3.18": "2025-11-12",
    },
    "release_attrs": {
        "logging-6.6": {"name": "logging-6.6", "product": "OCP Logging"},
        "quay-3.18": {"name": "quay-3.18", "product": "Quay"},
    },
}
