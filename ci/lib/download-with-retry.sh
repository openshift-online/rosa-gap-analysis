#!/usr/bin/env bash
# =============================================================================
# Library: download-with-retry.sh
# Description: Bounded-retry downloader for the tool installs in ci/Containerfile
#
# WHY
#   The build root failed in Prow when a single HTTP 504 was returned while
#   downloading the ROSA CLI zip:
#     STEP 13/22: RUN ... curl -fsSL "${ROSA_CLI_BASE_URL}/rosa_linux_${arch}.zip" ...
#     curl: (22) The requested URL returned error: 504
#   The nightly gap analysis never executed because one unretried gateway error
#   aborted the image build. A bounded retry keeps a single transient gateway
#   response from discarding the whole run.
#
# WHY NOT JUST `curl --retry`
#   `curl -fsSL --retry 4 --retry-delay 5 --retry-max-time 600` would fix the
#   observed 504 on its own, and it is the right starting point. It does print
#   one `curl: (22) ...` line per attempt, so basic diagnostics are not the
#   reason for this file. The reason is that curl 7.76.1 (the version in this
#   UBI9 image) has no setting between "too narrow" and "too broad".
#   Measured in the built image against a local server:
#     * `--retry 2` on a truncated transfer: 1 attempt, exit 18. curl does not
#       retry an interrupted transfer (nor 52 empty reply, 56 receive error,
#       16/92 HTTP/2 stream errors) unless --retry-all-errors is given.
#     * `--retry 2 --retry-all-errors` on a 404: 3 attempts. That flag also
#       retries permanent errors, which would discard the fail-fast property
#       this change is required to keep.
#   A reset HTTP/2 stream or a short read partway through a 120 MB tarball is
#   the same class of event as the 504 that caused the outage, so the middle
#   ground is what is wanted, and curl cannot express it here.
#   Two smaller gaps come along with the wrapper rather than motivating it:
#   curl treats a zero-length 2xx as success (always wrong for these four
#   multi-MB artifacts), and --remove-on-error only exists from curl 7.83, so a
#   failed download leaves a partial file behind. The partial file is harmless
#   inside these `&&` chains, since a failed RUN discards the layer; it is
#   cleaned up so the helper is safe for any caller that tolerates a failure.
#
# RETRY SCOPE (deliberately narrow)
#   Retried: the HTTP statuses curl's own --retry documents as transient
#            (408, 429, 500, 502, 503, 504), the network-level curl exits
#            listed below, and a 2xx that delivered an empty file.
#   Not retried: every other response. A permanent 404 (a tool version that
#            does not exist) fails on the first attempt, and so do TLS (35) and
#            send (55) failures, which point at configuration or a local fault
#            rather than at a flaky hop.
#   Exhaustion: exits with curl's non-zero status so the build still fails.
#
# DIAGNOSTICS
#   Attempt number, HTTP status, curl exit code and a short reason are written
#   to stderr so a failure is diagnosable from the build log alone. stdout is
#   left empty.
#   No part of the URL is ever logged. The destination path is used as the
#   artifact identifier instead: it is a literal in ci/Containerfile, whereas
#   the URL is assembled from build ARGs (OCM_CLI_BASE_URL, ROSA_CLI_BASE_URL)
#   that a downstream build may point at an internal mirror, and a path segment
#   or query parameter can itself carry a token. curl runs without
#   --show-error for the same reason: its messages name the host it failed to
#   resolve or connect to. The status and exit code this script prints carry
#   the same diagnostic information without the host.
#
# Usage: download-with-retry <url> <destination>
# Exit:  0 on success
#        2 on a usage or configuration error
#        curl's non-zero exit status on a permanent failure, or after the
#        attempt budget or the total time budget is exhausted
# =============================================================================

set -euo pipefail

# Per-attempt and overall time limits, sized for the largest artifact installed
# by ci/Containerfile (openshift-client-linux.tar.gz, ~120 MB): 300s covers that
# over a slow link. TOTAL_MAX_TIME caps the whole download so a sustained outage
# fails the build promptly instead of stalling it until the Prow step times out.
readonly CONNECT_TIMEOUT=20
readonly MAX_TIME=300

# Overridable so the regression tests can exercise the bounds quickly.
MAX_ATTEMPTS="${GAP_DOWNLOAD_MAX_ATTEMPTS:-4}"
RETRY_BASE_DELAY="${GAP_DOWNLOAD_RETRY_BASE_DELAY:-5}"
TOTAL_MAX_TIME="${GAP_DOWNLOAD_TOTAL_MAX_TIME:-600}"

# HTTP statuses curl's built-in --retry treats as transient.
readonly RETRYABLE_HTTP_CODES=" 408 429 500 502 503 504 "
# Network-level curl exits: a hop failed, not the request. 6 resolve host and
# 7 connect (curl itself retries 6, and 7 only behind --retry-connrefused);
# 16 and 92 HTTP/2 protocol and stream errors; 18 partial transfer; 28 timeout
# (curl retries this one); 52 empty reply; 56 receive error. Everything curl
# will not retry here needs --retry-all-errors, which would also retry a 404.
# Anything outside this list is treated as permanent.
readonly RETRYABLE_CURL_EXITS=" 6 7 16 18 28 52 56 92 "

log() {
    printf 'download-with-retry: %s\n' "$*" >&2
}

usage() {
    printf 'Usage: %s <url> <destination>\n' "$(basename "$0")" >&2
}

# Reject anything that is not a plain integer before it reaches $(( )), where
# bash would otherwise evaluate it as an arithmetic expression.
check_count() {
    local name="$1" value="$2" pattern="$3"
    if [[ ! "${value}" =~ ${pattern} ]]; then
        log "${name} must be an integer matching ${pattern}, got '${value}'"
        return 2
    fi
}

# Short, host-free explanation of a curl exit code, so dropping --show-error
# costs no diagnostic information.
curl_reason() {
    case "$1" in
        6)  printf 'could not resolve host' ;;
        7)  printf 'could not connect' ;;
        16|92) printf 'HTTP/2 protocol error' ;;
        18) printf 'transfer closed before completion' ;;
        22) printf 'HTTP error response' ;;
        23) printf 'could not write destination' ;;
        28) printf 'timed out' ;;
        35) printf 'TLS connect error' ;;
        52) printf 'empty reply from server' ;;
        55) printf 'send error' ;;
        56) printf 'receive error' ;;
        *)  printf 'curl error' ;;
    esac
}

main() {
    if [[ $# -ne 2 || -z "${1}" || -z "${2}" ]]; then
        usage
        return 2
    fi

    local url="$1"
    # The destination, not the URL, is this download's identifier in the log.
    local dest="$2"

    check_count GAP_DOWNLOAD_MAX_ATTEMPTS "${MAX_ATTEMPTS}" '^[1-9][0-9]*$' || return 2
    check_count GAP_DOWNLOAD_RETRY_BASE_DELAY "${RETRY_BASE_DELAY}" '^[0-9]+$' || return 2
    check_count GAP_DOWNLOAD_TOTAL_MAX_TIME "${TOTAL_MAX_TIME}" '^[1-9][0-9]*$' || return 2

    local attempt=1
    local delay size remaining attempt_max_time reason
    # Carried across iterations so the give-up line can name the last cause.
    local http_code="" curl_exit=0

    while true; do
        # Never let one attempt outlive the overall budget. --max-time 0 means
        # "no timeout" to curl, so the <= 0 check must come before the call.
        remaining=$(( TOTAL_MAX_TIME - SECONDS ))
        attempt_max_time="${MAX_TIME}"
        if [[ ${remaining} -lt ${attempt_max_time} ]]; then
            attempt_max_time="${remaining}"
        fi
        if [[ ${attempt_max_time} -le 0 ]]; then
            log "giving up after ${TOTAL_MAX_TIME}s total: ${dest} (last HTTP ${http_code:-none}, last curl exit ${curl_exit})"
            return $(( curl_exit > 0 ? curl_exit : 28 ))
        fi

        http_code=""
        curl_exit=0
        http_code=$(curl \
            --silent --location --fail \
            --connect-timeout "${CONNECT_TIMEOUT}" \
            --max-time "${attempt_max_time}" \
            --write-out '%{http_code}' \
            --output "${dest}" \
            "${url}") || curl_exit=$?

        size=0
        if [[ -f "${dest}" ]]; then
            size=$(wc -c <"${dest}")
        fi

        if [[ ${curl_exit} -eq 0 && ${size} -gt 0 ]]; then
            log "attempt ${attempt}/${MAX_ATTEMPTS} succeeded: ${dest} (HTTP ${http_code}, ${size} bytes)"
            return 0
        fi

        # Drop any empty or partial file so a later build step cannot consume it.
        if [[ -f "${dest}" ]]; then
            rm -f "${dest}" || log "could not remove incomplete output ${dest}"
        fi

        local retryable=0
        if [[ ${curl_exit} -eq 0 ]]; then
            # A 2xx that delivered nothing is as useless as a 504, and retrying
            # it is cheaper than failing a later step on a zero-byte binary.
            retryable=1
            reason="empty body"
        elif [[ ${curl_exit} -eq 22 ]]; then
            # HTTP error reported by --fail: retry only transient statuses.
            reason="HTTP status"
            if [[ "${RETRYABLE_HTTP_CODES}" == *" ${http_code} "* ]]; then
                retryable=1
            fi
        else
            reason="transport error: $(curl_reason "${curl_exit}")"
            if [[ "${RETRYABLE_CURL_EXITS}" == *" ${curl_exit} "* ]]; then
                retryable=1
            fi
        fi

        if [[ ${retryable} -eq 0 ]]; then
            log "attempt ${attempt}/${MAX_ATTEMPTS} failed permanently (${reason}): ${dest} (HTTP ${http_code:-none}, curl exit ${curl_exit}); not retrying"
            return "${curl_exit}"
        fi

        log "attempt ${attempt}/${MAX_ATTEMPTS} failed with a transient error (${reason}): ${dest} (HTTP ${http_code:-none}, curl exit ${curl_exit})"

        if [[ ${attempt} -ge ${MAX_ATTEMPTS} ]]; then
            log "giving up after ${MAX_ATTEMPTS} attempts: ${dest} (last HTTP ${http_code:-none}, last curl exit ${curl_exit})"
            # An empty body leaves curl_exit at 0; report a failure regardless.
            return $(( curl_exit == 0 ? 1 : curl_exit ))
        fi

        delay=$(( RETRY_BASE_DELAY * 2 ** (attempt - 1) ))
        log "retrying in ${delay}s"
        sleep "${delay}"
        attempt=$(( attempt + 1 ))
    done
}

main "$@"
