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
