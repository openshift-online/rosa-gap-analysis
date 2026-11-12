"""Offline fixtures for the accepted release streams API.

Mirrors the shape of
https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted
at the 4.x → 5.x major transition: stable releases for a major live in
"{major}-stable" and the stream also carries that major's RC builds.
"""

import json

# 4.x GA line plus a 5.x major that has already shipped z-streams (5.0.1, 5.0.0).
# No 5.x version appears in 4-stable — that is exactly why hardcoding "4-stable"
# made `--version 5.0` fail with "No stable versions found for 5.0.x".
ACCEPTED_STREAMS = {
    "4-dev-preview": ["4.23.0-ec.2", "4.23.0-ec.1"],
    "4-stable": [
        "4.22.21", "4.22.20", "4.22.19",
        "4.22.0-rc.4", "4.22.0-rc.3",
        "4.21.30", "4.21.29",
    ],
    "5-dev-preview": ["5.1.0-ec.1", "5.1.0-ec.0"],
    "5-stable": ["5.0.1", "5.0.0", "5.0.0-rc.8", "5.0.0-rc.7"],
    "5.0.0-0.nightly": ["5.0.0-0.nightly-2026-11-01-000000"],
}

# 5.0 the day it went GA: a single z-stream, with RC builds still in 5-stable.
# The RC builds must not be mistaken for a previous z-stream.
ACCEPTED_STREAMS_AT_GA = {
    "4-stable": ["4.22.21", "4.22.20"],
    "5-stable": ["5.0.0", "5.0.0-rc.8", "5.0.0-rc.7"],
}

# A 5-stable stream that exists but holds nothing, and no 6-stable at all.
ACCEPTED_STREAMS_EMPTY_5 = {
    "4-stable": ["4.22.21", "4.22.20"],
    "4-dev-preview": ["4.23.0-ec.2"],
    "5-stable": [],
}


def as_json(streams):
    """Serialize a fixture the way the accepted-streams API would."""
    return json.dumps(streams)
