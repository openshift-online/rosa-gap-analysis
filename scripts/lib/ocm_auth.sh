#!/bin/bash
# OCM authentication utilities
# Handles OCM login using token or client credentials

# Authenticate to OCM environment using available credentials
# Checks credentials in order: OCM_TOKEN, OCM_CLIENT_ID+OCM_CLIENT_SECRET
# Returns: 0 on successful login or no credentials available, 1 on error
ocm_authenticate() {
    local url_args=()
    if [[ -n "${OCM_URL:-}" ]]; then
        url_args+=(--url "${OCM_URL}")
        log_info "OCM environment: ${OCM_URL}"
        unset OCM_URL
    fi

    if [[ -n "${OCM_TOKEN:-}" ]]; then
        log_info "Logging in to OCM using OCM_TOKEN"
        ocm login --token "${OCM_TOKEN}" "${url_args[@]}"
    elif [[ -n "${OCM_CLIENT_ID:-}" && -n "${OCM_CLIENT_SECRET:-}" ]]; then
        log_info "Logging in to OCM using client_id and secret"
        ocm login --client-id "${OCM_CLIENT_ID}" --client-secret "${OCM_CLIENT_SECRET}" "${url_args[@]}"
    else
        log_info "Cannot log in to OCM due to missing credentials"
    fi
}

# Load OCM credentials from the ci-operator credential mount into the variables
# ocm_authenticate() consumes. The file keys match the rosa-e2e / gap-analysis
# credential collection used by the gap-analysis CI config (sso-client-id,
# sso-client-secret). Values already set in the environment take precedence
# (e.g. when the job exports OCM_CLIENT_ID / OCM_CLIENT_SECRET directly).
ocm_load_credentials() {
    local dir="${1:-/var/run/ocm-credentials}"
    if [[ -z "${OCM_CLIENT_ID:-}" && -f "${dir}/sso-client-id" ]]; then
        export OCM_CLIENT_ID="$(<"${dir}/sso-client-id")"
    fi
    if [[ -z "${OCM_CLIENT_SECRET:-}" && -f "${dir}/sso-client-secret" ]]; then
        export OCM_CLIENT_SECRET="$(<"${dir}/sso-client-secret")"
    fi
}
