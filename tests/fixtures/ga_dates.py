"""Offline fixture for the Sippy releases API GA-date payload.

Mirrors the `ga_dates` object of
https://sippy.dptools.openshift.org/api/releases as served when the 4.20
nightly failed to resolve a GA version: 19 OpenShift minors plus `logging-6.6`,
a release line that is not an OpenShift version at all. Keys are what matters
here, so the dates are the real ones but are never asserted on.
"""

# Keyed by release LINE, not by product — `logging-6.6` is the reason the
# resolvers must select version-shaped keys instead of converting every key.
LIVE_GA_DATES = {
    "3.11": "2018-10-10",
    "4.6": "2020-10-27",
    "4.7": "2021-02-24",
    "4.8": "2021-07-27",
    "4.9": "2021-10-18",
    "4.10": "2022-03-10",
    "4.11": "2022-08-10",
    "4.12": "2023-01-17",
    "4.13": "2023-05-17",
    "4.14": "2023-10-31",
    "4.15": "2024-02-28",
    "4.16": "2024-06-27",
    "4.17": "2024-10-01",
    "4.18": "2025-02-25",
    "4.19": "2025-06-17",
    "4.20": "2025-10-21",
    "4.21": "2026-02-03",
    "4.22": "2026-06-09",
    "5.0": "2026-11-03",
    "logging-6.6": "2026-07-14",
}

# The newest OpenShift minor in LIVE_GA_DATES. `logging-6.6` sorts after it as
# a string, so the expected value is not simply the last key.
LIVE_GA_DATES_LATEST = "5.0"

# No key is an OpenShift version, so there is nothing to resolve.
NO_OPENSHIFT_GA_DATES = {
    "logging-6.6": "2026-07-14",
    "four-twenty": "2025-10-21",
}

# Keys that are near-misses rather than obvious foreign lines. None is a bare
# numeric major.minor, so none may be treated as an OpenShift GA version.
# "4.21\n" is the sharp one: an unanchored `$` (jq's Oniguruma and Python's re
# both match before a trailing newline) lets it through, and it then reaches
# the numeric conversion the filter exists to protect.
NON_VERSION_KEYS = ("4", "4.x", "4.21.3", "v4.21", " 4.21", "4.21 ", "4.21\n")
