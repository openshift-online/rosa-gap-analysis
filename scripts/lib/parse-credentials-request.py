#!/usr/bin/env python3
"""
Parse OpenShift CredentialsRequest YAML files and extract cloud-specific permission data.

Supports:
- AWS: Extracts spec.providerSpec.statementEntries (IAM policy statements)
- GCP: Extracts spec.providerSpec.permissions (GCP IAM permissions)
"""

import argparse
import json
import sys
import yaml


def parse_aws_credentials_request(data):
    """
    Extract AWS IAM statement entries from CredentialsRequest.

    Returns: List of IAM statement entries or empty list
    """
    try:
        entries = data.get('spec', {}).get('providerSpec', {}).get('statementEntries', [])
        return entries if entries else []
    except (AttributeError, TypeError):
        return []


def parse_gcp_credentials_request(data):
    """
    Extract GCP IAM permissions from CredentialsRequest.

    Returns: List of GCP permission strings or empty list
    """
    try:
        permissions = data.get('spec', {}).get('providerSpec', {}).get('permissions', [])
        return permissions if permissions else []
    except (AttributeError, TypeError):
        return []


def main():
    parser = argparse.ArgumentParser(
        description='Parse OpenShift CredentialsRequest YAML files'
    )
    parser.add_argument(
        '--cloud',
        required=True,
        choices=['aws', 'gcp'],
        help='Cloud platform (aws or gcp)'
    )
    parser.add_argument(
        '--file',
        required=True,
        help='Path to CredentialsRequest YAML file'
    )

    args = parser.parse_args()

    try:
        # Load YAML file
        with open(args.file, 'r') as f:
            data = yaml.safe_load(f)

        # Extract cloud-specific data
        if args.cloud == 'aws':
            result = parse_aws_credentials_request(data)
        elif args.cloud == 'gcp':
            result = parse_gcp_credentials_request(data)
        else:
            result = []

        # Output as JSON
        print(json.dumps(result))
        return 0

    except FileNotFoundError:
        print(json.dumps([]), file=sys.stdout)
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        return 1
    except yaml.YAMLError as e:
        print(json.dumps([]), file=sys.stdout)
        print(f"Error: Failed to parse YAML: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(json.dumps([]), file=sys.stdout)
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
