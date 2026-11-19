#!/bin/bash
# OpenShift Release Information Library
# Functions to query OpenShift release data from Sippy and OCP releases

# Source logging utilities if available
_OPENSHIFT_RELEASES_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${_OPENSHIFT_RELEASES_SCRIPT_DIR}/logging.sh" ]]; then
    source "${_OPENSHIFT_RELEASES_SCRIPT_DIR}/logging.sh"
fi

# API endpoints
readonly SIPPY_API="https://sippy.dptools.openshift.org/api/releases"
readonly ACCEPTED_STREAMS_API="https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestreams/accepted"
# RELEASE_STREAM_BASE still needed for pullspec/nightly functions (accepted API doesn't provide pullspecs)
readonly RELEASE_STREAM_BASE="https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream"

# Cache for accepted streams (to avoid multiple API calls)
_ACCEPTED_STREAMS_CACHE=""

# Versions listed in a resolution-failure diagnostic
# (mirrors _DIAGNOSTIC_SAMPLE_SIZE in openshift_releases.py)
readonly _DIAGNOSTIC_SAMPLE_SIZE=10

# jq predicate dropping RC/EC pre-releases. X-stable carries that major's RC
# builds alongside its stable releases, so every "stable"/z-stream filter needs
# it (mirrors is_prerelease_version() in openshift_releases.py).
readonly _JQ_NOT_PRERELEASE='((contains("-rc.") or contains("-ec.")) | not)'

# The accepted-streams API publishes one stable and one dev-preview stream per
# MAJOR version (4-stable, 5-stable, 4-dev-preview, 5-dev-preview). Always derive
# the stream name from the version being resolved — hardcoding "4-stable" makes
# every 5.x resolution read an unrelated stream and report "no versions found".
# Usage: stable_stream_for_version "5.0" → "5-stable"
stable_stream_for_version() {
    local version="$1"
    echo "${version%%.*}-stable"
}

# Usage: dev_preview_stream_for_version "5.1" → "5-dev-preview"
dev_preview_stream_for_version() {
    local version="$1"
    echo "${version%%.*}-dev-preview"
}

# Log bounded, non-sensitive diagnostics when a stream lookup finds no match.
# Prints the stream that was selected, the public API it came from, and at most
# _DIAGNOSTIC_SAMPLE_SIZE of the newest versions that stream does contain, so a
# CI artifact alone shows why resolution failed. Never prints the full API response.
# Call it once per stream that was consulted.
# Usage: _log_stream_lookup_failure <stream> <version-line> <streams-json>
_log_stream_lookup_failure() {
    local stream="$1"
    local version_line="$2"
    local streams="$3"
    local has_stream
    local count
    local sample
    local available_streams

    has_stream=$(echo "$streams" | jq -r --arg s "$stream" 'has($s)' 2>/dev/null)

    if [[ -z "$has_stream" ]]; then
        _log_diagnostic "Could not parse the accepted streams response from ${ACCEPTED_STREAMS_API}"
        return 0
    fi

    if [[ "$has_stream" != "true" ]]; then
        available_streams=$(echo "$streams" | \
            jq -r 'keys | map(select(endswith("-stable") or endswith("-dev-preview"))) | join(", ")' 2>/dev/null)
        _log_diagnostic "Stream ${stream} is not present in ${ACCEPTED_STREAMS_API} (available: ${available_streams:-none})"
        return 0
    fi

    count=$(echo "$streams" | jq -r --arg s "$stream" '.[$s] | length' 2>/dev/null)
    sample=$(echo "$streams" | \
        jq -r --arg s "$stream" --argjson n "$_DIAGNOSTIC_SAMPLE_SIZE" '.[$s][0:$n] | join(", ")' 2>/dev/null)
    _log_diagnostic "Searched ${stream} from ${ACCEPTED_STREAMS_API} for ${version_line}.x"
    _log_diagnostic "Stream ${stream} holds ${count:-0} accepted version(s); newest: ${sample:-none}"
}

# Emit a diagnostic line through log_info when available, stderr otherwise.
_log_diagnostic() {
    if command -v log_info &>/dev/null; then
        log_info "$1"
    else
        echo "Info: $1" >&2
    fi
}

# Helper function: curl with retry logic and improved error reporting
# Provides defense-in-depth with two retry layers:
#   1. curl's built-in retry (handles transient connection errors)
#   2. Shell-level retry loop with exponential backoff (handles HTTP errors and empty responses)
# Usage: _curl_with_retry <url>
# Returns: Response body on stdout
# Exit: 0 on success, 1 on failure after all retries exhausted
#
# A returned body is always byte-complete. Bash command substitution silently
# discards NUL bytes, so a response carrying one would be handed to the caller
# as a shorter, clean-looking string — and a caller that validates the body it
# receives would be validating something the server never sent. The bytes are
# counted on the temporary file, before the capture, and a response that cannot
# survive it is rejected rather than truncated.
_curl_with_retry() {
    local url="$1"
    local max_attempts=3
    local attempt=1
    local backoff=5
    local http_code
    local body
    local tmpfile
    local total_bytes
    local text_bytes
    local nul_count

    while [[ $attempt -le $max_attempts ]]; do
        tmpfile=$(mktemp)

        # curl retry flags handle transient connection errors;
        # shell loop handles HTTP errors and empty responses
        http_code=$(curl -s \
            --retry 3 --retry-delay 5 --retry-all-errors \
            -w '%{http_code}' \
            -o "$tmpfile" \
            "$url" 2>/dev/null) || true

        # Count NUL bytes on the file, before the substitution below drops
        # them. wc and tr are already required by this library, so this adds
        # no runtime dependency. Fail closed: if the count cannot be taken,
        # the body is not provably intact, so it is not returned.
        total_bytes=$(wc -c <"$tmpfile" 2>/dev/null | tr -d '[:space:]' 2>/dev/null) || true
        text_bytes=$(LC_ALL=C tr -d '\0' <"$tmpfile" 2>/dev/null | wc -c 2>/dev/null | tr -d '[:space:]' 2>/dev/null) || true
        if [[ "$total_bytes" =~ ^[0-9]+$ ]] && [[ "$text_bytes" =~ ^[0-9]+$ ]]; then
            nul_count=$((total_bytes - text_bytes))
        else
            nul_count="unmeasured"
        fi

        body=$(cat "$tmpfile" 2>/dev/null) || true
        rm -f "$tmpfile"

        # Success: 2xx status, non-empty body, and nothing lost to the capture.
        if [[ "$http_code" =~ ^2[0-9][0-9]$ ]] && [[ -n "$body" ]] && [[ "$nul_count" == "0" ]]; then
            echo "$body"
            return 0
        fi

        # Log failure details for diagnostics
        local body_snippet="${body:0:200}"
        local failure_detail="URL=${url} HTTP_STATUS=${http_code} RESPONSE=${body_snippet:-<empty>}"
        if [[ "$nul_count" != "0" ]]; then
            # The snippet is deliberately dropped here: the body is known to be
            # mangled, so only the endpoint, the status and the count are named.
            failure_detail="URL=${url} HTTP_STATUS=${http_code} RESPONSE_NUL_BYTES=${nul_count}"
        fi
        if command -v log_warning &>/dev/null; then
            log_warning "API request failed (attempt ${attempt}/${max_attempts}): ${failure_detail}"
        else
            echo "Warning: API request failed (attempt ${attempt}/${max_attempts}): ${failure_detail}" >&2
        fi

        if [[ $attempt -lt $max_attempts ]]; then
            if command -v log_info &>/dev/null; then
                log_info "Retrying in ${backoff}s..."
            else
                echo "Info: Retrying in ${backoff}s..." >&2
            fi
            sleep "$backoff"
            backoff=$((backoff * 2))
        fi

        attempt=$((attempt + 1))
    done

    # All retry attempts exhausted
    if command -v log_error &>/dev/null; then
        log_error "API request failed after ${max_attempts} attempts: URL=${url} HTTP_STATUS=${http_code}"
    else
        echo "Error: API request failed after ${max_attempts} attempts: URL=${url} HTTP_STATUS=${http_code}" >&2
    fi
    return 1
}

# Helper function to extract minor version number from version string
# Usage: extract_minor_version "4.21"
# Returns: Minor version number (e.g., "21")
extract_minor_version() {
    local version="$1"
    echo "$version" | cut -d'.' -f2
}

# Helper function to extract base version from candidate version string
# Usage: extract_version_from_candidate "4.22.0-ec.3"
# Returns: Base version (e.g., "4.22")
extract_version_from_candidate() {
    local candidate="$1"
    # Extract major.minor from candidate version (e.g., "4.22.0-ec.3" -> "4.22")
    echo "$candidate" | sed -E 's/^([0-9]+\.[0-9]+)\..*/\1/'
}

# Helper function to extract base version from stable version string
# Usage: extract_version_from_stable "4.21.6"
# Returns: Base version (e.g., "4.21")
extract_version_from_stable() {
    local stable="$1"
    # Extract major.minor from stable version (e.g., "4.21.6" -> "4.21")
    echo "$stable" | sed -E 's/^([0-9]+\.[0-9]+)\..*/\1/'
}

# Validate that candidate version belongs to the expected version
# Usage: validate_candidate_belongs_to_version <candidate> <expected_version>
# Arguments:
#   $1 - Candidate version (e.g., "4.22.0-ec.3")
#   $2 - Expected version (e.g., "4.22")
# Returns: 0 if valid (candidate belongs to expected version), 1 otherwise
validate_candidate_belongs_to_version() {
    local candidate="$1"
    local expected_version="$2"

    if [[ -z "$candidate" ]] || [[ -z "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Both candidate and expected version required for validation"
        else
            echo "Error: Both candidate and expected version required for validation" >&2
        fi
        return 1
    fi

    local candidate_base=$(extract_version_from_candidate "$candidate")

    if [[ "$candidate_base" != "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Candidate version ($candidate) does not belong to expected version ($expected_version), found $candidate_base instead"
        else
            echo "Error: Candidate version ($candidate) does not belong to expected version ($expected_version)" >&2
        fi
        return 1
    fi

    return 0
}

# Validate that stable version belongs to the expected version
# Usage: validate_stable_belongs_to_version <stable> <expected_version>
# Arguments:
#   $1 - Stable version (e.g., "4.21.6")
#   $2 - Expected version (e.g., "4.21")
# Returns: 0 if valid (stable belongs to expected version), 1 otherwise
validate_stable_belongs_to_version() {
    local stable="$1"
    local expected_version="$2"

    if [[ -z "$stable" ]] || [[ -z "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Both stable and expected version required for validation"
        else
            echo "Error: Both stable and expected version required for validation" >&2
        fi
        return 1
    fi

    local stable_base=$(extract_version_from_stable "$stable")

    if [[ "$stable_base" != "$expected_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Stable version ($stable) does not belong to expected version ($expected_version), found $stable_base instead"
        else
            echo "Error: Stable version ($stable) does not belong to expected version ($expected_version)" >&2
        fi
        return 1
    fi

    return 0
}

# Map an untrusted jq `type` result onto a closed whitelist, so a crafted or
# corrupted response can never inject text into a log line. The case list is
# the whitelist; anything else collapses to "unknown".
# Usage: _safe_json_type "$(... | jq -r 'type')" → object|array|string|number|boolean|null|unknown
_safe_json_type() {
    # Echo the matched literal rather than the input, so the result is
    # independent of the input even under `shopt -s nocasematch`.
    case "$1" in
        object) echo "object" ;;
        array) echo "array" ;;
        string) echo "string" ;;
        number) echo "number" ;;
        boolean) echo "boolean" ;;
        null) echo "null" ;;
        *) echo "unknown" ;;
    esac
}

# Map an untrusted value onto a non-negative integer, or "unknown". Keeps
# counts and lengths safe to interpolate into a diagnostic.
# Usage: _safe_count "$(... | jq -r 'length')"
_safe_count() {
    if [[ "$1" =~ ^[0-9]+$ ]]; then
        echo "$1"
    else
        echo "unknown"
    fi
}

# True when the body carries a number JSON cannot express.
#
# jq's parser is a superset of JSON: it accepts the bare literals `Infinity`,
# `-Infinity`, `NaN` and `nan`, which RFC 8259 does not allow. A body using
# them therefore parses cleanly and reaches the extract filter, so an exit
# status alone cannot stand in for "this was JSON".
#
# A finite literal too large for a double (1e400) reads back as infinite and is
# rejected too. That is intentional: this endpoint returns version strings and
# dates, so such a value is already an unexpected payload, and a number that
# cannot be read back faithfully is not one to resolve a version from.
#
# Scalars are inspected as parse events (`--stream`) rather than by walking
# the built value, because object construction is lossy: on a duplicate key
# the later value replaces the earlier one, so
# `{"ga_dates":{"4.21":"d"},"extra":Infinity,"extra":0}` would present a
# wholly finite object to a recursive walk while still being a body no JSON
# parser should have accepted. The event stream reports both values. `any`
# short-circuits, so a large payload is not read further than the first hit.
#
# Prints nothing. Exit: 0 when a non-finite number is present, 1 otherwise
# (including when the body does not parse at all — the caller's parse probe
# owns that case, and jq's own stderr stays suppressed either way).
# Usage: _json_has_non_finite_number <body>
_json_has_non_finite_number() {
    # A --stream event is [path, value] for a scalar and [path] for a close.
    printf '%s' "$1" | jq -e -n --stream \
        'any(inputs; length == 2 and (.[1] | type == "number") and (.[1] | isinfinite or isnan))' \
        >/dev/null 2>&1
}

# Classify why a Sippy payload did not yield a GA version.
# Returns a fixed phrase built only from literals, whitelisted JSON type names
# and integers — never the response body, a body excerpt, headers or jq's
# stderr, any of which can echo response content into a CI artifact.
# root_rc/doc_count come from the caller's parse probe, so the exit status is
# judged before the output is sanitized.
# Usage: _classify_ga_dates_failure <body> <jq-exit-code> <root-rc> <doc-count>
_classify_ga_dates_failure() {
    local body="$1"
    local jq_status="$2"
    local root_rc
    local doc_count
    local bytes
    local root_type
    local has_ga_dates
    local ga_dates_type
    local key_count

    # Sanitize here too: the function is export -f'd, so it must not rely on a
    # caller having validated these before interpolating them into a log line.
    jq_status=$(_safe_count "$jq_status")
    root_rc=$(_safe_count "$3")
    doc_count=$(_safe_count "$4")

    # 126/127 are the shell's "not executable"/"not found" statuses. Probe the
    # command as well: a jq shim can exit 127 while jq is genuinely on PATH,
    # and an unreadable jq exits 126 on a payload that is perfectly valid.
    if ! command -v jq >/dev/null 2>&1 || [[ "$jq_status" == "126" ]] || [[ "$jq_status" == "127" ]]; then
        echo "jq is unavailable or not executable (exit ${jq_status})"
        return 0
    fi

    # Trailing newlines were already stripped by the capturing substitutions.
    bytes=$(_safe_count "$(printf '%s' "$body" | wc -c 2>/dev/null | tr -d '[:space:]' 2>/dev/null)")

    # jq exits 0 and prints nothing on blank input, which would otherwise be
    # reported as invalid JSON alongside a success exit code.
    if [[ -z "${body//[[:space:]]/}" ]]; then
        echo "response body is blank (${bytes} byte(s))"
        return 0
    fi

    # jq streams values as it reads them, so output alone does not prove the
    # whole body parsed: a trailing-garbage payload prints a type and then
    # fails. Judge the probe's exit status first, before any sanitized output.
    if [[ "$root_rc" != "0" ]]; then
        echo "response is not a single valid JSON document (jq exit ${root_rc}, ${bytes} byte(s))"
        return 0
    fi

    # A JSON *stream* parses cleanly but is still not the single object this
    # endpoint is expected to return.
    if [[ "$doc_count" != "1" ]]; then
        echo "response holds ${doc_count} JSON document(s), expected exactly 1 (${bytes} byte(s))"
        return 0
    fi

    # jq accepts the non-standard literals Infinity, -Infinity and NaN, so a
    # clean exit status above does not by itself mean the body was JSON.
    # Recomputed here rather than passed in: unlike the exit status, this is a
    # boolean the function can establish for itself from the body.
    if _json_has_non_finite_number "$body"; then
        # Kept terse: every diagnostic line stays under the 200-char bound the
        # tests pin, and this one already sits close to it.
        echo "response contains a non-finite number (${bytes} byte(s))"
        return 0
    fi

    root_type=$(_safe_json_type "$(printf '%s' "$body" | jq -r 'type' 2>/dev/null)")
    if [[ "$root_type" != "object" ]]; then
        echo "response root is JSON ${root_type}, expected object (${bytes} byte(s))"
        return 0
    fi

    # `|| true` keeps this safe if a caller enables `shopt -s inherit_errexit`.
    has_ga_dates=$(printf '%s' "$body" | jq -r 'has("ga_dates")' 2>/dev/null) || true
    if [[ "$has_ga_dates" != "true" ]]; then
        echo "response has no ga_dates field (${bytes} byte(s))"
        return 0
    fi

    ga_dates_type=$(_safe_json_type "$(printf '%s' "$body" | jq -r '.ga_dates | type' 2>/dev/null)")
    if [[ "$ga_dates_type" != "object" ]]; then
        echo "ga_dates is JSON ${ga_dates_type}, expected object (${bytes} byte(s))"
        return 0
    fi

    key_count=$(_safe_count "$(printf '%s' "$body" | jq -r '.ga_dates | keys | length' 2>/dev/null)")
    if [[ "$key_count" == "0" ]]; then
        echo "ga_dates is an empty object (${bytes} byte(s))"
        return 0
    fi

    echo "ga_dates holds ${key_count} key(s), at least one of which is not a numeric version"
}

# Get the latest GA (generally available) OpenShift version
# Usage: get_latest_ga_version
# Returns: Version string (e.g., "4.21") or empty string on failure
# Exit: 0 on success, 1 on failure
#
# The fetch and the parse are separate stages with separate diagnostics. A
# successful HTTP response whose payload cannot be parsed is reported as a
# parse failure rather than being folded into the fetch error, so a CI
# artifact alone distinguishes an unreachable API from an unexpected payload.
# jq's stderr stays suppressed because it can quote the response; its exit
# code and a fixed classification are reported instead. That guarantee covers
# the parse stage added here; the fetch stage keeps _curl_with_retry's own
# long-standing HTTP logging unchanged.
get_latest_ga_version() {
    local body
    local version
    local jq_status
    local root_types
    local root_rc
    local doc_count
    local non_finite
    local reason

    # Stage 1: fetch. _curl_with_retry logs its own HTTP-level diagnostics.
    if ! body=$(_curl_with_retry "${SIPPY_API}"); then
        _log_ga_version_failure "request to ${SIPPY_API} returned no usable response"
        return 1
    fi

    # Stage 2a: the body must parse completely, as exactly one JSON document,
    # before any value read out of it can be trusted. jq emits values as it
    # reads them, so it prints a type and then fails on trailing garbage, and
    # prints one line per document on a JSON stream. Capture the exit status
    # here, before the output is sanitized, and count the documents.
    if root_types=$(printf '%s' "$body" | jq -r 'type' 2>/dev/null); then
        root_rc=0
    else
        root_rc=$?
    fi
    # Counted with wc rather than grep so this adds no new runtime dependency.
    if [[ -z "$root_types" ]]; then
        doc_count=0
    else
        doc_count=$(_safe_count "$(printf '%s\n' "$root_types" | wc -l 2>/dev/null | tr -d '[:space:]' 2>/dev/null)")
    fi

    # Stage 2a (cont.): a clean exit status is necessary but not sufficient.
    # jq also accepts Infinity/-Infinity/NaN, which JSON does not, so the body
    # can parse and still not be JSON. Probe for them separately.
    if _json_has_non_finite_number "$body"; then
        non_finite=1
    else
        non_finite=0
    fi

    # Stage 2b: extract. Keep jq's exit code; `if` keeps `set -e` from aborting.
    if version=$(printf '%s' "$body" | \
        jq -r '.ga_dates | keys | sort_by(split(".") | map(tonumber)) | last' 2>/dev/null); then
        jq_status=0
    else
        jq_status=$?
    fi

    # root_rc is redundant in practice (both jq runs parse the same stream, so
    # a probe failure implies an extract failure) but is kept as an explicit,
    # independent "the body parsed completely" precondition.
    if [[ $root_rc -ne 0 ]] || [[ "$doc_count" != "1" ]] || [[ $non_finite -ne 0 ]] || \
       [[ $jq_status -ne 0 ]] || [[ -z "$version" ]] || [[ "$version" == "null" ]]; then
        reason=$(_classify_ga_dates_failure "$body" "$jq_status" "$root_rc" "$doc_count")
        _log_ga_version_failure "could not read ga_dates from ${SIPPY_API}: ${reason}"
        return 1
    fi

    echo "$version"
    return 0
}

# Report a GA-version resolution failure: the long-standing error line that
# marks the failure, followed by one bounded, non-sensitive diagnostic naming
# the stage that failed.
# Usage: _log_ga_version_failure <fixed-classification>
_log_ga_version_failure() {
    if command -v log_error &>/dev/null; then
        log_error "Failed to fetch latest GA version from Sippy API"
    else
        echo "Error: Failed to fetch latest GA version" >&2
    fi
    _log_diagnostic "GA version resolution failed: $1"
}

# Fetch all accepted release streams (cached to avoid multiple API calls)
# Usage: fetch_accepted_streams
# Returns: JSON object with accepted streams: {"4-stable": [...], "4-dev-preview": [...]}
# Exit: 0 on success, 1 on failure
fetch_accepted_streams() {
    # Return cached value if available
    if [[ -n "$_ACCEPTED_STREAMS_CACHE" ]]; then
        echo "$_ACCEPTED_STREAMS_CACHE"
        return 0
    fi

    # Fetch and cache the accepted streams
    _ACCEPTED_STREAMS_CACHE=$(_curl_with_retry "$ACCEPTED_STREAMS_API")

    if [[ -z "$_ACCEPTED_STREAMS_CACHE" ]] || [[ "$_ACCEPTED_STREAMS_CACHE" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch accepted release streams"
        else
            echo "Error: Failed to fetch accepted release streams" >&2
        fi
        return 1
    fi

    echo "$_ACCEPTED_STREAMS_CACHE"
    return 0
}

# Get the latest development version (not yet GA)
# Ensures dev version is exactly 1 minor version ahead of GA
# Usage: get_latest_dev_version
# Returns: Version string (e.g., "4.22") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_dev_version() {
    local ga_version
    local ga_minor
    local expected_dev_minor
    local expected_dev_version
    local all_releases

    # Get latest GA version first
    ga_version=$(get_latest_ga_version) || return 1

    # Calculate expected dev version (GA + 1), keeping the GA major (5.0 → 5.1)
    ga_minor=$(extract_minor_version "$ga_version")
    expected_dev_minor=$((ga_minor + 1))
    expected_dev_version="${ga_version%%.*}.${expected_dev_minor}"

    # Get all available releases
    all_releases=$(_curl_with_retry "${SIPPY_API}" | \
        jq -r '.releases[]' 2>/dev/null)

    if [[ -z "$all_releases" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch releases from Sippy API"
        else
            echo "Error: Failed to fetch releases from Sippy API" >&2
        fi
        return 1
    fi

    # Check if expected dev version exists in releases
    if echo "$all_releases" | grep -q "^${expected_dev_version}$"; then
        echo "$expected_dev_version"
        return 0
    else
        if command -v log_error &>/dev/null; then
            log_error "Expected dev version ${expected_dev_version} (GA+1) not found in available releases"
        else
            echo "Error: Expected dev version ${expected_dev_version} (GA+1) not found in available releases" >&2
        fi
        return 1
    fi
}

# Get the latest candidate (RC or EC) version for GA+1 from accepted streams
# First checks {major}-stable for RC version, falls back to {major}-dev-preview for EC version
# Usage: get_latest_candidate_version
# Returns: Latest candidate version (e.g., "4.22.0-rc.0" or "4.22.0-ec.5") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_candidate_version() {
    local ga_version
    local dev_version
    local streams
    local latest_candidate

    # Get GA version first
    ga_version=$(get_latest_ga_version) || return 1

    # Calculate dev version (GA + 1), keeping the GA major (4.21 → 4.22, 5.0 → 5.1)
    local ga_major
    local ga_minor
    ga_major=$(echo "$ga_version" | cut -d. -f1)
    ga_minor=$(echo "$ga_version" | cut -d. -f2)
    local dev_minor=$((ga_minor + 1))
    dev_version="${ga_major}.${dev_minor}"

    # Streams are per-major: resolve 4.x against 4-stable, 5.x against 5-stable
    local stable_stream
    local dev_preview_stream
    stable_stream=$(stable_stream_for_version "$dev_version")
    dev_preview_stream=$(dev_preview_stream_for_version "$dev_version")

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Priority 1: Check {major}-stable for RC version (e.g., 4.22.0-rc.*, 5.1.0-rc.*)
    # Versions are already sorted newest first
    latest_candidate=$(echo "$streams" | \
        jq -r --arg stream "$stable_stream" --arg dev "$dev_version" '.[$stream][]? | select(startswith($dev + ".0-rc."))' 2>/dev/null | head -1)

    if [[ -n "$latest_candidate" ]] && [[ "$latest_candidate" != "null" ]]; then
        if command -v log_info &>/dev/null; then
            log_info "Found RC version in ${stable_stream}: $latest_candidate"
        fi
        echo "$latest_candidate"
        return 0
    fi

    # Priority 2: No RC in stable, check {major}-dev-preview for EC version (e.g., 4.22.0-ec.*)
    latest_candidate=$(echo "$streams" | \
        jq -r --arg stream "$dev_preview_stream" --arg dev "$dev_version" '.[$stream][]? | select(startswith($dev + ".0-ec."))' 2>/dev/null | head -1)

    if [[ -z "$latest_candidate" ]] || [[ "$latest_candidate" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch candidate version for ${dev_version}.x (no RC in ${stable_stream}, no EC in ${dev_preview_stream})"
        else
            echo "Error: Failed to fetch candidate version for ${dev_version}.x" >&2
        fi
        _log_stream_lookup_failure "$stable_stream" "$dev_version" "$streams"
        _log_stream_lookup_failure "$dev_preview_stream" "$dev_version" "$streams"
        return 1
    fi

    if command -v log_info &>/dev/null; then
        log_info "Found EC version in ${dev_preview_stream}: $latest_candidate"
    fi

    echo "$latest_candidate"
    return 0
}

# Get the latest stable version from accepted streams
# Ensures stable version belongs to GA version
# Usage: get_latest_stable_version [version_line]   # defaults to the latest GA line
# Returns: Latest stable version (e.g., "4.21.11") or empty string on failure
# Exit: 0 on success, 1 on failure
get_latest_stable_version() {
    local ga_version="${1:-}"
    local streams
    local stable_stream
    local latest_stable

    # Default to the latest GA version (e.g., "4.21") when no line is requested
    if [[ -z "$ga_version" ]]; then
        ga_version=$(get_latest_ga_version) || return 1
    fi

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Select the stable stream for this version's major (4.21 → 4-stable, 5.0 → 5-stable)
    stable_stream=$(stable_stream_for_version "$ga_version")

    # Filter the stable stream by GA version line (e.g., 4.21.x) and drop pre-releases:
    # X-stable also carries RC builds (5.0.0-rc.8), which are not stable releases.
    # Versions are already sorted newest first in the accepted API
    latest_stable=$(echo "$streams" | \
        jq -r --arg stream "$stable_stream" --arg ga "$ga_version" \
        '.[$stream][]? | select(startswith($ga + ".") and '"$_JQ_NOT_PRERELEASE"')' 2>/dev/null | head -1)

    if [[ -z "$latest_stable" ]] || [[ "$latest_stable" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest stable version for ${ga_version}.x from ${stable_stream} accepted stream"
        else
            echo "Error: Failed to fetch latest stable version for ${ga_version}.x from ${stable_stream} accepted stream" >&2
        fi
        _log_stream_lookup_failure "$stable_stream" "$ga_version" "$streams"
        return 1
    fi

    # Validate that stable belongs to GA version (should always pass now due to filter)
    if ! validate_stable_belongs_to_version "$latest_stable" "$ga_version"; then
        return 1
    fi

    echo "$latest_stable"
    return 0
}

# Get the latest stable version pullspec from stable stream
# Ensures stable version belongs to GA version
# Usage: get_latest_stable_pullspec
# Returns: Pullspec for latest stable version (e.g., "quay.io/openshift-release-dev/ocp-release:4.21.6-x86_64")
# Exit: 0 on success, 1 on failure
get_latest_stable_pullspec() {
    local api_url
    local ga_version
    local stable_stream
    local stable_version
    local pullspec

    # Get GA version first (e.g., "4.21")
    ga_version=$(get_latest_ga_version) || return 1

    # Build API URL for this major's stable stream (amd64)
    stable_stream=$(stable_stream_for_version "$ga_version")
    api_url="${RELEASE_STREAM_BASE}/${stable_stream}/tags"

    # Fetch tags and filter to only those matching GA version line (e.g., 4.21.x)
    # Get both name and pullspec for the first matching tag
    local result
    result=$(_curl_with_retry "$api_url" | \
        jq -r --arg ga "$ga_version" '.tags[] | select(.name | startswith($ga + ".") and '"$_JQ_NOT_PRERELEASE"') | {name: .name, pullSpec: .pullSpec} | @json' 2>/dev/null | head -1)

    if [[ -z "$result" ]] || [[ "$result" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch latest stable version for ${ga_version}.x from ${stable_stream} stream"
        else
            echo "Error: Failed to fetch latest stable version for ${ga_version}.x from ${stable_stream} stream" >&2
        fi
        return 1
    fi

    stable_version=$(echo "$result" | jq -r '.name')
    pullspec=$(echo "$result" | jq -r '.pullSpec')

    # Validate that stable belongs to GA version (should always pass now due to filter)
    if ! validate_stable_belongs_to_version "$stable_version" "$ga_version"; then
        return 1
    fi

    if [[ -z "$pullspec" ]] || [[ "$pullspec" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch pullspec for stable version ${stable_version}"
        else
            echo "Error: Failed to fetch pullspec for stable version ${stable_version}" >&2
        fi
        return 1
    fi

    echo "$pullspec"
    return 0
}

# Get the latest candidate (RC or EC) version pullspec
# First checks {major}-stable for RC, falls back to {major}-dev-preview for EC
# Usage: get_latest_candidate_pullspec
# Returns: Pullspec for latest candidate version (e.g., "quay.io/openshift-release-dev/ocp-release:4.22.0-rc.1-x86_64" or "registry.ci.openshift.org/ocp/release:4.22.0-ec.3")
# Exit: 0 on success, 1 on failure
get_latest_candidate_pullspec() {
    local ga_version
    local dev_version
    local candidate_version
    local pullspec
    local stable_api_url
    local dev_api_url

    # Get GA version first
    ga_version=$(get_latest_ga_version) || return 1

    # Calculate dev version (GA + 1), keeping the GA major (4.21 → 4.22, 5.0 → 5.1)
    local ga_major
    local ga_minor
    ga_major=$(echo "$ga_version" | cut -d. -f1)
    ga_minor=$(echo "$ga_version" | cut -d. -f2)
    local dev_minor=$((ga_minor + 1))
    dev_version="${ga_major}.${dev_minor}"

    # Step 1: Check {major}-stable stream for RC version
    stable_api_url="${RELEASE_STREAM_BASE}/$(stable_stream_for_version "$dev_version")/tags"

    # Get candidate version and pullspec from stable stream
    local stable_result
    stable_result=$(_curl_with_retry "$stable_api_url" | \
        jq -r --arg dev "$dev_version" '.tags[] | select(.name | startswith($dev + ".0-rc.")) | {name: .name, pullSpec: .pullSpec} | @json' 2>/dev/null | head -1)

    if [[ -n "$stable_result" ]] && [[ "$stable_result" != "null" ]]; then
        candidate_version=$(echo "$stable_result" | jq -r '.name')
        pullspec=$(echo "$stable_result" | jq -r '.pullSpec')

        if [[ -n "$pullspec" ]] && [[ "$pullspec" != "null" ]]; then
            echo "$pullspec"
            return 0
        fi
    fi

    # Step 2: No RC in stable, check {major}-dev-preview stream for EC version
    dev_api_url="${RELEASE_STREAM_BASE}/$(dev_preview_stream_for_version "$dev_version")/tags"

    # Get candidate version and pullspec from dev-preview stream
    local dev_result
    dev_result=$(_curl_with_retry "$dev_api_url" | \
        jq -r --arg dev "$dev_version" '.tags[] | select(.name | startswith($dev + ".0-ec.")) | {name: .name, pullSpec: .pullSpec} | @json' 2>/dev/null | head -1)

    if [[ -z "$dev_result" ]] || [[ "$dev_result" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch candidate pullspec for ${dev_version}.x"
        else
            echo "Error: Failed to fetch candidate pullspec for ${dev_version}.x" >&2
        fi
        return 1
    fi

    candidate_version=$(echo "$dev_result" | jq -r '.name')
    pullspec=$(echo "$dev_result" | jq -r '.pullSpec')

    if [[ -z "$pullspec" ]] || [[ "$pullspec" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch pullspec for candidate version ${candidate_version}"
        else
            echo "Error: Failed to fetch pullspec for candidate version ${candidate_version}" >&2
        fi
        return 1
    fi

    echo "$pullspec"
    return 0
}

# Get the latest nightly build pull spec for a given version
# Usage: get_latest_nightly_pullspec <version>
# Arguments:
#   $1 - Version (e.g., "4.22")
# Returns: Pull spec (e.g., "registry.ci.openshift.org/ocp/release:4.22.0-0.nightly-2026-03-13-184504")
# Exit: 0 on success, 1 on failure
get_latest_nightly_pullspec() {
    local version="$1"
    local api_url
    local pullspec

    if [[ -z "$version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Version parameter required"
        else
            echo "Error: Version parameter required" >&2
        fi
        return 1
    fi

    # Build API URL (amd64)
    api_url="${RELEASE_STREAM_BASE}/${version}.0-0.nightly/latest?rel=1"

    pullspec=$(_curl_with_retry "$api_url" | jq -r '.pullSpec' 2>/dev/null)

    if [[ -z "$pullspec" ]] || [[ "$pullspec" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch nightly pullspec for version ${version}"
        else
            echo "Error: Failed to fetch nightly pullspec for version ${version}" >&2
        fi
        return 1
    fi

    echo "$pullspec"
    return 0
}

# Get the latest nightly version tag for dev version
# Usage: get_latest_dev_nightly_version
# Returns: Nightly version tag (e.g., "4.22.0-0.nightly-2026-03-13-184504")
# Exit: 0 on success, 1 on failure
get_latest_dev_nightly_version() {
    local dev_version
    local api_url
    local nightly_version

    # Get dev version first
    dev_version=$(get_latest_dev_version) || return 1

    # Build API URL for nightly stream (amd64)
    api_url="${RELEASE_STREAM_BASE}/${dev_version}.0-0.nightly/latest?rel=1"

    # Fetch nightly version tag
    nightly_version=$(_curl_with_retry "$api_url" | jq -r '.name' 2>/dev/null)

    if [[ -z "$nightly_version" ]] || [[ "$nightly_version" == "null" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to fetch nightly version for dev version ${dev_version}"
        else
            echo "Error: Failed to fetch nightly version for dev version ${dev_version}" >&2
        fi
        return 1
    fi

    echo "$nightly_version"
    return 0
}

# Get the latest nightly pullspec for dev version
# Usage: get_latest_dev_nightly_pullspec
# Returns: Nightly pullspec (e.g., "registry.ci.openshift.org/ocp/release:4.22.0-0.nightly-2026-03-13-184504")
# Exit: 0 on success, 1 on failure
get_latest_dev_nightly_pullspec() {
    local dev_version

    # Get dev version first
    dev_version=$(get_latest_dev_version) || return 1

    # Use existing function to get nightly pullspec
    get_latest_nightly_pullspec "$dev_version"
}

# Get all unique minor versions from accepted streams
# Usage: get_all_minor_versions_from_accepted_streams
# Returns: Newline-separated sorted list of minor versions (e.g., "4.18\n4.19\n4.20\n4.23\n5.0\n...")
# Exit: 0 on success, 1 on failure
get_all_minor_versions_from_accepted_streams() {
    local streams
    local all_versions

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Extract all versions from ALL streams (not just 4-stable and 4-dev-preview)
    # This includes 5-stable, 5-dev-preview, and version-specific nightly/CI streams
    # Then extract minor version (4.21.11 → 4.21, 4.22.0-rc.0 → 4.22, 5.0.0-ec.1 → 5.0)
    all_versions=$(echo "$streams" | \
        jq -r '.[] | arrays | .[]' 2>/dev/null | \
        sed -E 's/^([0-9]+\.[0-9]+).*/\1/' | \
        sort -u -V)

    if [[ -z "$all_versions" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to extract minor versions from accepted streams"
        else
            echo "Error: Failed to extract minor versions from accepted streams" >&2
        fi
        return 1
    fi

    echo "$all_versions"
    return 0
}

# Get the previous z-stream version for a given minor version
# Usage: get_previous_z_stream_version "4.21"
# Returns: Previous z-stream version (e.g., "4.21.10" if latest is "4.21.11")
# Exit: 0 on success (with version or skip message), 1 on failure
get_previous_z_stream_version() {
    local minor_version="$1"
    local streams
    local stable_stream
    local versions
    local version_count
    local previous_version

    if [[ -z "$minor_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Minor version parameter required"
        else
            echo "Error: Minor version parameter required" >&2
        fi
        return 1
    fi

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Get all versions for this minor version line from the major's stable stream
    # (4.21 → 4-stable, 5.0 → 5-stable). RC/EC builds also live in X-stable but
    # are not z-streams, so they are excluded from the z-stream history.
    # Versions are already sorted newest first
    stable_stream=$(stable_stream_for_version "$minor_version")
    versions=$(echo "$streams" | \
        jq -r --arg stream "$stable_stream" --arg minor "$minor_version" \
        '.[$stream][]? | select(startswith($minor + ".") and '"$_JQ_NOT_PRERELEASE"')' 2>/dev/null)

    if [[ -z "$versions" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "No stable versions found for ${minor_version}.x"
        else
            echo "Error: No stable versions found for ${minor_version}.x" >&2
        fi
        _log_stream_lookup_failure "$stable_stream" "$minor_version" "$streams"
        return 1
    fi

    # Count how many versions we have
    version_count=$(echo "$versions" | wc -l)

    if [[ $version_count -eq 1 ]]; then
        if command -v log_info &>/dev/null; then
            log_info "Only one z-stream version available for ${minor_version}, skipping gap analysis"
        else
            echo "Info: Only one z-stream version available for ${minor_version}, skipping gap analysis" >&2
        fi
        # Return special marker for skip scenario
        echo "SKIP"
        return 0
    fi

    # Get the second version (previous z-stream)
    previous_version=$(echo "$versions" | sed -n '2p')

    if [[ -z "$previous_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Failed to get previous z-stream version for ${minor_version}"
        else
            echo "Error: Failed to get previous z-stream version for ${minor_version}" >&2
        fi
        return 1
    fi

    echo "$previous_version"
    return 0
}

# Get the latest version for a given minor version line
# Priority: stable > candidate (RC or EC) > nightly
# Usage: get_latest_version_for_line "4.22"
# Returns: Latest version (e.g., "4.22.5" or "4.22.0-rc.0" or "4.22.0-0.nightly-...")
# Exit: 0 on success, 1 on failure
# Get the latest version for baseline
# Precedence: stable > candidate (RC/EC) > CI > nightly
# Usage: get_latest_version_baseline_priority "4.22"
# Returns: Latest version using baseline precedence
# Exit: 0 on success, 1 on failure
get_latest_version_baseline_priority() {
    local minor_version="$1"
    local streams
    local stable_stream
    local dev_preview_stream
    local nightly_stream
    local ci_stream
    local stable_version
    local rc_version
    local ec_version
    local ci_version
    local nightly_version

    if [[ -z "$minor_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Minor version parameter required"
        else
            echo "Error: Minor version parameter required" >&2
        fi
        return 1
    fi

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Streams are per-major (4.22 → 4-stable, 5.0 → 5-stable)
    stable_stream=$(stable_stream_for_version "$minor_version")
    dev_preview_stream=$(dev_preview_stream_for_version "$minor_version")
    nightly_stream="${minor_version}.0-0.nightly"
    ci_stream="${minor_version}.0-0.ci"

    # Priority 1: Stable version (e.g., 4.22.5, 5.0.5)
    stable_version=$(echo "$streams" | \
        jq -r --arg stream "$stable_stream" --arg minor "$minor_version" '.[$stream][]? | select(startswith($minor + ".") and '"$_JQ_NOT_PRERELEASE"')' 2>/dev/null | head -1)

    if [[ -n "$stable_version" ]] && [[ "$stable_version" != "null" ]]; then
        echo "$stable_version"
        return 0
    fi

    # Priority 2: RC from X-stable
    rc_version=$(echo "$streams" | \
        jq -r --arg stream "$stable_stream" --arg minor "$minor_version" '.[$stream][]? | select(startswith($minor + ".0-rc."))' 2>/dev/null | head -1)

    if [[ -n "$rc_version" ]] && [[ "$rc_version" != "null" ]]; then
        echo "$rc_version"
        return 0
    fi

    # Priority 3: EC from X-dev-preview
    ec_version=$(echo "$streams" | \
        jq -r --arg stream "$dev_preview_stream" --arg minor "$minor_version" '.[$stream][]? | select(startswith($minor + ".0-ec."))' 2>/dev/null | head -1)

    if [[ -n "$ec_version" ]] && [[ "$ec_version" != "null" ]]; then
        echo "$ec_version"
        return 0
    fi

    # Priority 4: CI from X.Y.0-0.ci
    ci_version=$(echo "$streams" | jq -r --arg stream "$ci_stream" '.[$stream][0]' 2>/dev/null)

    if [[ -n "$ci_version" ]] && [[ "$ci_version" != "null" ]]; then
        echo "$ci_version"
        return 0
    fi

    # Priority 5: Nightly from X.Y.0-0.nightly
    nightly_version=$(echo "$streams" | jq -r --arg stream "$nightly_stream" '.[$stream][0]' 2>/dev/null)

    if [[ -n "$nightly_version" ]] && [[ "$nightly_version" != "null" ]]; then
        echo "$nightly_version"
        return 0
    fi

    if command -v log_error &>/dev/null; then
        log_error "No version found for ${minor_version} (checked stable, RC, EC, CI, nightly)"
    else
        echo "Error: No version found for ${minor_version}" >&2
    fi
    _log_stream_lookup_failure "$stable_stream" "$minor_version" "$streams"
    _log_stream_lookup_failure "$dev_preview_stream" "$minor_version" "$streams"
    _log_stream_lookup_failure "$ci_stream" "$minor_version" "$streams"
    _log_stream_lookup_failure "$nightly_stream" "$minor_version" "$streams"
    return 1
}

# Get the latest version for target
# Precedence: candidate (RC/EC) > CI > nightly
# Usage: get_latest_version_target_priority "4.22"
# Returns: Latest version using target precedence
# Exit: 0 on success, 1 on failure
get_latest_version_target_priority() {
    local minor_version="$1"
    local streams
    local stable_stream
    local dev_preview_stream
    local nightly_stream
    local ci_stream
    local rc_version
    local ec_version
    local ci_version
    local nightly_version

    if [[ -z "$minor_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Minor version parameter required"
        else
            echo "Error: Minor version parameter required" >&2
        fi
        return 1
    fi

    # Fetch accepted streams
    streams=$(fetch_accepted_streams) || return 1

    # Streams are per-major (4.22 → 4-stable, 5.0 → 5-stable)
    stable_stream=$(stable_stream_for_version "$minor_version")
    dev_preview_stream=$(dev_preview_stream_for_version "$minor_version")
    nightly_stream="${minor_version}.0-0.nightly"
    ci_stream="${minor_version}.0-0.ci"

    # Priority 1: RC from X-stable
    rc_version=$(echo "$streams" | \
        jq -r --arg stream "$stable_stream" --arg minor "$minor_version" '.[$stream][]? | select(startswith($minor + ".0-rc."))' 2>/dev/null | head -1)

    if [[ -n "$rc_version" ]] && [[ "$rc_version" != "null" ]]; then
        echo "$rc_version"
        return 0
    fi

    # Priority 2: EC from X-dev-preview
    ec_version=$(echo "$streams" | \
        jq -r --arg stream "$dev_preview_stream" --arg minor "$minor_version" '.[$stream][]? | select(startswith($minor + ".0-ec."))' 2>/dev/null | head -1)

    if [[ -n "$ec_version" ]] && [[ "$ec_version" != "null" ]]; then
        echo "$ec_version"
        return 0
    fi

    # Priority 3: CI from X.Y.0-0.ci
    ci_version=$(echo "$streams" | jq -r --arg stream "$ci_stream" '.[$stream][0]' 2>/dev/null)

    if [[ -n "$ci_version" ]] && [[ "$ci_version" != "null" ]]; then
        echo "$ci_version"
        return 0
    fi

    # Priority 4: Nightly from X.Y.0-0.nightly
    nightly_version=$(echo "$streams" | jq -r --arg stream "$nightly_stream" '.[$stream][0]' 2>/dev/null)

    if [[ -n "$nightly_version" ]] && [[ "$nightly_version" != "null" ]]; then
        echo "$nightly_version"
        return 0
    fi

    if command -v log_error &>/dev/null; then
        log_error "No version found for ${minor_version} (checked candidate, CI, nightly)"
    else
        echo "Error: No version found for ${minor_version}" >&2
    fi
    _log_stream_lookup_failure "$stable_stream" "$minor_version" "$streams"
    _log_stream_lookup_failure "$dev_preview_stream" "$minor_version" "$streams"
    _log_stream_lookup_failure "$ci_stream" "$minor_version" "$streams"
    _log_stream_lookup_failure "$nightly_stream" "$minor_version" "$streams"
    return 1
}

# Get the latest version for a given minor version line
# Uses baseline precedence (stable > candidate > CI > nightly)
# This function is kept for backward compatibility
# Usage: get_latest_version_for_line "4.22"
# Returns: Latest version using baseline precedence
# Exit: 0 on success, 1 on failure
get_latest_version_for_line() {
    get_latest_version_baseline_priority "$1"
}

# Resolve BASE and TARGET versions from a single OPENSHIFT_VERSION
# Get special baseline version mapping for major version transitions
# Usage: get_special_baseline_mapping "5.0"
# Returns: Special baseline version if exists, empty string otherwise
# Exit: 0 always
get_special_baseline_mapping() {
    local target_version="$1"

    # Special mappings for 5.x transition
    # OpenShift upgrade path:
    # - 4.19 → 4.20 → 4.21 → 4.22 → 4.23 (continues)
    # - 4.22 → 5.0 (first major bump)
    # - 4.23 → 5.1 (second major bump)
    # - 5.1 → 5.2 → 5.3 → ... (normal progression)
    case "$target_version" in
        "5.0")
            echo "4.22"
            ;;
        "5.1")
            echo "4.23"
            ;;
        *)
            echo ""
            ;;
    esac
}

# Get special target version mapping for major version transitions
# Inverse of get_special_baseline_mapping
# Usage: get_special_target_mapping "4.22"
# Returns: Special target version if exists (e.g., "5.0"), empty string otherwise
# Exit: 0 always
get_special_target_mapping() {
    local baseline_version="$1"

    case "$baseline_version" in
        "4.22")
            echo "5.0"
            ;;
        "4.23")
            echo "5.1"
            ;;
        *)
            echo ""
            ;;
    esac
}

# Usage: resolve_openshift_version "4.23"
# Returns: Two values on stdout: BASE_VERSION TARGET_VERSION (space-separated)
# Exit: 0 on success (or skip scenario), 1 on failure
resolve_openshift_version() {
    local openshift_version="$1"
    local ga_version
    local all_minor_versions
    local all_releases
    local version_exists
    local is_ga_or_older
    local base_version
    local target_version
    local previous_version
    local previous_is_ga

    if [[ -z "$openshift_version" ]]; then
        if command -v log_error &>/dev/null; then
            log_error "OPENSHIFT_VERSION parameter required"
        else
            echo "Error: OPENSHIFT_VERSION parameter required" >&2
        fi
        return 1
    fi

    # Step 1: Get GA version from Sippy
    ga_version=$(get_latest_ga_version) || return 1

    # Step 2: Get all minor versions from accepted streams (sorted)
    # This includes both GA and pre-GA versions
    all_minor_versions=$(get_all_minor_versions_from_accepted_streams) || return 1

    # Step 3: Check if OPENSHIFT_VERSION exists in accepted streams
    version_exists=$(echo "$all_minor_versions" | grep -c "^${openshift_version}$" || true)

    if [[ $version_exists -eq 0 ]]; then
        if command -v log_error &>/dev/null; then
            log_error "Version ${openshift_version} not found in accepted streams"
            log_error "Available versions: $(echo "$all_minor_versions" | tr '\n' ' ')"
        else
            echo "Error: Version ${openshift_version} not found in accepted streams" >&2
            echo "Available versions: $(echo "$all_minor_versions" | tr '\n' ' ')" >&2
        fi
        return 1
    fi

    # Step 4: Compare openshift_version with ga_version
    # Extract major and minor version numbers for comparison
    local openshift_major
    local openshift_minor
    local ga_major
    local ga_minor
    openshift_major=$(echo "$openshift_version" | cut -d'.' -f1)
    openshift_minor=$(extract_minor_version "$openshift_version")
    ga_major=$(echo "$ga_version" | cut -d'.' -f1)
    ga_minor=$(extract_minor_version "$ga_version")

    # Compare major version first, then minor version
    if [[ $openshift_major -lt $ga_major ]] || ( [[ $openshift_major -eq $ga_major ]] && [[ $openshift_minor -le $ga_minor ]] ); then
        # GA or older version → z-stream comparison
        is_ga_or_older=true

        if command -v log_info &>/dev/null; then
            log_info "Version ${openshift_version} is GA or older (GA=${ga_version}), using z-stream comparison"
        fi

        # Get previous z-stream version
        # (check the assignment directly: under `set -e` a `$?` test after a
        # failing command substitution is never reached)
        if ! base_version=$(get_previous_z_stream_version "$openshift_version"); then
            return 1
        fi

        # Check for skip scenario
        if [[ "$base_version" == "SKIP" ]]; then
            if command -v log_info &>/dev/null; then
                log_info "Skipping gap analysis for ${openshift_version} (only one z-stream available)"
            fi
            echo "SKIP SKIP"
            return 0
        fi

        # Get latest z-stream version (baseline precedence since both are stable)
        if ! target_version=$(get_latest_version_baseline_priority "$openshift_version"); then
            return 1
        fi

    else
        # Pre-GA version → cross-minor comparison
        is_ga_or_older=false

        if command -v log_info &>/dev/null; then
            log_info "Version ${openshift_version} is pre-GA (GA=${ga_version}), using cross-minor comparison"
        fi

        # Check for special baseline mapping first (e.g., 5.0 → 4.22, 5.1 → 4.23)
        local special_baseline
        special_baseline=$(get_special_baseline_mapping "$openshift_version")

        if [[ -n "$special_baseline" ]]; then
            # Use special baseline mapping
            previous_version="$special_baseline"
            if command -v log_info &>/dev/null; then
                log_info "Using special baseline mapping: ${openshift_version} → ${special_baseline}"
            fi
        else
            # Find previous version in sorted list
            previous_version=$(echo "$all_minor_versions" | grep -B1 "^${openshift_version}$" | head -1)

            if [[ -z "$previous_version" ]] || [[ "$previous_version" == "$openshift_version" ]]; then
                if command -v log_error &>/dev/null; then
                    log_error "Cannot find previous version for ${openshift_version} in sorted list"
                else
                    echo "Error: Cannot find previous version for ${openshift_version}" >&2
                fi
                return 1
            fi

            if command -v log_info &>/dev/null; then
                log_info "Previous version in sorted list: ${previous_version}"
            fi
        fi

        # Check if previous version is GA or pre-GA
        local previous_major
        local previous_minor
        previous_major=$(echo "$previous_version" | cut -d'.' -f1)
        previous_minor=$(extract_minor_version "$previous_version")

        # Compare major version first, then minor version
        if [[ $previous_major -lt $ga_major ]] || ( [[ $previous_major -eq $ga_major ]] && [[ $previous_minor -le $ga_minor ]] ); then
            # Previous is GA → get latest stable
            previous_is_ga=true

            if command -v log_info &>/dev/null; then
                log_info "Previous version ${previous_version} is GA, using latest stable"
            fi

            # Resolve the previous line explicitly: with a major transition the
            # previous version (e.g. 4.23) is not always the latest GA line (5.0)
            if ! base_version=$(get_latest_stable_version "$previous_version"); then
                return 1
            fi

        else
            # Previous is pre-GA → get latest using baseline precedence
            previous_is_ga=false

            if command -v log_info &>/dev/null; then
                log_info "Previous version ${previous_version} is pre-GA, using baseline precedence (stable > candidate > CI > nightly)"
            fi

            if ! base_version=$(get_latest_version_baseline_priority "$previous_version"); then
                return 1
            fi
        fi

        # Get target version using target precedence
        if command -v log_info &>/dev/null; then
            log_info "Target version ${openshift_version} using target precedence (candidate > CI > nightly)"
        fi

        if ! target_version=$(get_latest_version_target_priority "$openshift_version"); then
            return 1
        fi
    fi

    # Return both versions
    echo "$base_version $target_version"
    return 0
}

# Export functions for use in other scripts
export -f _curl_with_retry
export -f _log_diagnostic
export -f _log_stream_lookup_failure
export -f _safe_json_type
export -f _safe_count
export -f _json_has_non_finite_number
export -f _classify_ga_dates_failure
export -f _log_ga_version_failure
export -f stable_stream_for_version
export -f dev_preview_stream_for_version
export -f extract_minor_version
export -f extract_version_from_candidate
export -f extract_version_from_stable
export -f validate_candidate_belongs_to_version
export -f validate_stable_belongs_to_version
export -f get_latest_ga_version
export -f get_latest_dev_version
export -f get_latest_candidate_version
export -f get_latest_candidate_pullspec
export -f get_latest_stable_version
export -f get_latest_stable_pullspec
export -f get_latest_nightly_pullspec
export -f get_latest_dev_nightly_version
export -f get_latest_dev_nightly_pullspec
export -f get_all_minor_versions_from_accepted_streams
export -f get_previous_z_stream_version
export -f get_latest_version_for_line
export -f get_special_baseline_mapping
export -f get_special_target_mapping
export -f get_latest_version_baseline_priority
export -f get_latest_version_target_priority
export -f resolve_openshift_version

# If script is executed directly (not sourced), provide CLI interface
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
        --latest-ga)
            get_latest_ga_version
            ;;
        --latest-dev)
            get_latest_dev_version
            ;;
        --latest-stable)
            get_latest_stable_version "${2:-}"
            ;;
        --latest-stable-pullspec)
            get_latest_stable_pullspec
            ;;
        --latest-candidate)
            get_latest_candidate_version
            ;;
        --latest-candidate-pullspec)
            get_latest_candidate_pullspec
            ;;
        --latest-nightly)
            get_latest_dev_nightly_version
            ;;
        --latest-nightly-pullspec)
            get_latest_dev_nightly_pullspec
            ;;
        --nightly)
            if [[ -z "${2:-}" ]]; then
                echo "Usage: $0 --nightly <version>" >&2
                exit 1
            fi
            get_latest_nightly_pullspec "${2}"
            ;;
        --resolve-version)
            if [[ -z "${2:-}" ]]; then
                echo "Usage: $0 --resolve-version <version>" >&2
                exit 1
            fi
            resolve_openshift_version "${2}"
            ;;
        --all-minor-versions)
            get_all_minor_versions_from_accepted_streams
            ;;
        --previous-z-stream)
            if [[ -z "${2:-}" ]]; then
                echo "Usage: $0 --previous-z-stream <version>" >&2
                exit 1
            fi
            get_previous_z_stream_version "${2}"
            ;;
        --latest-for-line)
            if [[ -z "${2:-}" ]]; then
                echo "Usage: $0 --latest-for-line <version>" >&2
                exit 1
            fi
            get_latest_version_for_line "${2}"
            ;;
        --help|-h|"")
            cat <<EOF
OpenShift Release Information Library

Usage: $0 <command> [options]

Commands:
  --latest-ga                      Get latest GA version
  --latest-dev                     Get latest development version (GA+1)
  --latest-stable [version]        Get latest stable version (defaults to the GA line)
  --latest-stable-pullspec         Get pullspec for latest stable version
  --latest-candidate               Get latest candidate version (for dev version)
  --latest-candidate-pullspec      Get pullspec for latest candidate version
  --latest-nightly                 Get latest nightly version (for dev version)
  --latest-nightly-pullspec        Get pullspec for latest nightly version (for dev version)
  --nightly <version>              Get latest nightly pullspec for specific version
  --resolve-version <version>      Resolve BASE and TARGET versions from single version
  --all-minor-versions             Get all minor versions from accepted streams (sorted)
  --previous-z-stream <version>    Get previous z-stream version for a minor version
  --latest-for-line <version>      Get latest version for a minor version line
  --help, -h                       Show this help

Examples:
  $0 --latest-ga                      # Output: 4.21 (from Sippy API)
  $0 --latest-dev                     # Output: 4.22 (always GA+1)
  $0 --latest-stable                  # Output: 4.21.11 (latest GA line, from that major's stable stream)
  $0 --latest-stable 5.0              # Output: 5.0.1   (latest 5.0.x from 5-stable)
  $0 --latest-stable-pullspec         # Output: quay.io/openshift-release-dev/ocp-release:4.21.11-x86_64
  $0 --latest-candidate               # Output: 4.22.0-rc.0 or 4.22.0-ec.5 (RC from {major}-stable, or EC from {major}-dev-preview)
  $0 --latest-candidate-pullspec      # Output: quay.io/.../4.22.0-rc.0-x86_64 or registry.ci.../4.22.0-ec.5
  $0 --latest-nightly                 # Output: 4.22.0-0.nightly-2026-03-13-184504 (dev version)
  $0 --latest-nightly-pullspec        # Output: registry.ci.openshift.org/ocp/release:4.22.0-0.nightly...
  $0 --nightly 4.22                   # Output: registry.ci.openshift.org/ocp/release:4.22...
  $0 --resolve-version 4.21           # Output: 4.21.10 4.21.11 (z-stream comparison for GA)
  $0 --resolve-version 4.23           # Output: 4.22.x 4.23.0-0.nightly-... (cross-minor for pre-GA)
  $0 --all-minor-versions             # Output: 4.18\n4.19\n4.20\n4.21\n4.22\n4.23
  $0 --previous-z-stream 4.21         # Output: 4.21.10 (if latest is 4.21.11)
  $0 --latest-for-line 4.22           # Output: 4.22.0-rc.0 or 4.22.0-ec.5 (stable > RC > EC > nightly)

Notes:
  - Dev version is always exactly 1 minor version ahead of GA (e.g., GA=4.21, Dev=4.22)
  - Stable versions are filtered from the version's own {major}-stable stream for that line only
    (e.g., 4.21.x from 4-stable, 5.0.x from 5-stable); RC/EC builds in that stream are excluded
  - Candidate versions: first checks {major}-stable for RC (e.g., 4.22.0-rc.*), falls back to {major}-dev-preview for EC (e.g., 4.22.0-ec.*)
  - All validation is performed automatically when fetching versions

Can also be sourced in other scripts:
  source $0
  ga_version=\$(get_latest_ga_version)
  dev_version=\$(get_latest_dev_version)
  stable=\$(get_latest_stable_version)
  stable_pullspec=\$(get_latest_stable_pullspec)
  candidate=\$(get_latest_candidate_version)
  candidate_pullspec=\$(get_latest_candidate_pullspec)
  nightly_version=\$(get_latest_dev_nightly_version)
  nightly_pullspec=\$(get_latest_dev_nightly_pullspec)
  nightly=\$(get_latest_nightly_pullspec "4.22")

Additional functions available when sourced:
  - get_latest_candidate_version
  - get_latest_dev_nightly_version
  - get_latest_dev_nightly_pullspec
  - validate_candidate_belongs_to_version
  - validate_stable_belongs_to_version
  - extract_minor_version
  - extract_version_from_candidate
  - extract_version_from_stable
  - get_all_minor_versions_from_accepted_streams
  - get_previous_z_stream_version
  - get_latest_version_for_line
  - resolve_openshift_version

EOF
            exit 0
            ;;
        *)
            echo "Error: Unknown command: ${1}" >&2
            echo "Run '$0 --help' for usage" >&2
            exit 1
            ;;
    esac
fi
