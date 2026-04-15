#!/bin/bash
#
# GCP WIF Template Validator
# Validates Google Cloud Workload Identity Federation templates for:
# - Service account ID length (max 25 characters)
# - Role ID length (max 50 characters)
# - Role ID format (role_name_v4.XX or service.permission)
#
# Usage: validate-wif-template.sh <path-to-vanilla.yaml>
#

set -euo pipefail

# Check if yq is installed
if ! command -v yq &> /dev/null; then
    echo "Error: yq is not installed. Please install yq to proceed."
    exit 1
fi

if [[ -z "${1:-}" ]]; then
  echo "File path not provided."
  exit 1
fi

if [[ ! -f "$1" ]]; then
  echo "Invalid file path."
  exit 1
fi

YAML_FILE="$1"
SERVICE_ACCOUNT_ID_LENGTH=25
SERVICE_ACCOUNT_ROLE_ID_LENGTH=50
ERROR_MESSAGE=""

# Checking service accounts
SERVICE_ACCOUNTS_IDS=$(yq e '.service_accounts[].id' "$YAML_FILE")
while IFS= read -r ID; do
    if (( ${#ID} > SERVICE_ACCOUNT_ID_LENGTH )); then
        ERROR_MESSAGE+=$"SERVICE ACCOUNT: '${ID}' is ${#ID} characters long.\n"
        ERROR_MESSAGE+=$"\tThe character limit for service accounts is ${SERVICE_ACCOUNT_ID_LENGTH} characters.\n"
    fi
done <<< "$SERVICE_ACCOUNTS_IDS"

# Checking roles
ROLE_IDS=$(yq e '.service_accounts[].roles[].id' "$YAML_FILE")
while IFS= read -r ID; do
    if (( ${#ID} > SERVICE_ACCOUNT_ROLE_ID_LENGTH )); then
        ERROR_MESSAGE+=$"ROLE: '${ID}' is ${#ID} characters long.\n"
    fi

    # Correct format examples:
    # role_name_v4.17 (custom names)
    # compute.storageAdmin (gcp permission format)
    if [[ ! ( "$ID" =~ ^[a-z0-9_]+_v4\.[0-9]+$ || "$ID" =~ ^[a-zA-Z]+(\.[a-zA-Z]+)+(\.\*)?$ ) ]]; then
        ERROR_MESSAGE+=$"ROLE: '$ID' wrong format.\n"
    fi
done <<< "$ROLE_IDS"


if [[ -n $ERROR_MESSAGE ]]; then
    echo -e "$ERROR_MESSAGE"
    exit 1
else
  echo "All checks passed successfully."
fi
