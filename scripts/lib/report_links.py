"""Resolve report locations from the ci-operator multi-stage pod contract."""

import json
import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import quote


def job_url():
    """Return a verified periodic single-strategy GCS root, or no remote URL."""
    try:
        spec = json.loads(os.environ.get('JOB_SPEC', '{}'))
        config = spec['decoration_config']['gcs_configuration']
        job = spec['job']
        build_id = spec['buildid']
        bucket = config['bucket']
        if spec['type'] != 'periodic' or config['path_strategy'] != 'single':
            return None
        if not all(isinstance(value, str) for value in (job, build_id, bucket)):
            return None
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', job) or job in ('.', '..'):
            return None
        if not re.fullmatch(r'[0-9]+', build_id) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', bucket):
            return None
        return f'https://storage.googleapis.com/{bucket}/logs/{job}/{build_id}'
    except (ValueError, KeyError, TypeError):
        return None


def artifact_location(path):
    """Map a file beneath ARTIFACT_DIR to this multi-stage pod's upload path."""
    local_path = Path(path).resolve()
    root = job_url()
    artifact_dir = os.environ.get('ARTIFACT_DIR')
    test = os.environ.get('JOB_NAME_SAFE', '')
    hostname = socket.gethostname()
    job = json.loads(os.environ['JOB_SPEC'])['job'] if root else ''
    if (not root or os.environ.get('OPENSHIFT_CI') != 'true'
            or not artifact_dir or not Path(artifact_dir).is_absolute()
            or Path(artifact_dir).name != 'artifacts'
            or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', test)
            or not job.endswith('-' + test)
            or not hostname.startswith(test + '-')):
        return str(local_path)
    step = hostname[len(test) + 1:]
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', step):
        return str(local_path)
    try:
        relative = local_path.relative_to(Path(artifact_dir).resolve())
    except ValueError:
        return str(local_path)
    return f'{root}/artifacts/{test}/{step}/artifacts/{quote(relative.as_posix())}'


def build_log_location(path=None):
    """Link only an actual uploaded log file, not an unrelated job-root log."""
    return artifact_location(path) if path else None


if __name__ == '__main__':
    for report in sys.argv[1:]:
        print(artifact_location(report))
