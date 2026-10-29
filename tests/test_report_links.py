import json
import os
import shutil
import subprocess

import pytest

import report_links
from tests.conftest import ROOT, generate_combined_report


JOB = 'periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-5-0'
BUILD_ID = '2115715812697313280'
ROOT_URL = f'https://storage.googleapis.com/test-platform-results-public/logs/{JOB}/{BUILD_ID}'
REPORT = 'gap-analysis-ocm-version-gate_4.22_to_5.0_20261029_080515.html'


@pytest.fixture
def ci_environment(monkeypatch, tmp_path):
    for name in ('JOB_SPEC', 'JOB_NAME', 'BUILD_ID', 'PROW_JOB_ID', 'JOB_NAME_SAFE',
                 'ARTIFACT_DIR', 'OPENSHIFT_CI', 'job', 'buildid', 'BUILD_LOG',
                 'OPENSHIFT_VERSION', 'OCM_TOKEN', 'OCM_CLIENT_ID', 'OCM_CLIENT_SECRET'):
        monkeypatch.delenv(name, raising=False)
    spec = {
        'type': 'periodic', 'job': JOB, 'buildid': BUILD_ID,
        'prowjobid': '50a10731-d0bd-4a75-83ad-a7efcf049229',
        'decoration_config': {'gcs_configuration': {
            'bucket': 'test-platform-results-public', 'path_strategy': 'single',
        }},
    }
    artifact_dir = tmp_path / 'artifacts'
    artifact_dir.mkdir()
    for name, value in {
        'JOB_SPEC': json.dumps(spec), 'JOB_NAME': JOB, 'BUILD_ID': BUILD_ID,
        'PROW_JOB_ID': spec['prowjobid'], 'JOB_NAME_SAFE': 'nightly-5-0',
        'OPENSHIFT_CI': 'true', 'ARTIFACT_DIR': str(artifact_dir),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(report_links.socket, 'gethostname', lambda: 'nightly-5-0-5-0-gap-analysis')
    return spec, artifact_dir


@pytest.mark.parametrize('extension', ['html', 'json'])
def test_run_report_path(ci_environment, extension):
    _, artifact_dir = ci_environment
    filename = REPORT.removesuffix('html') + extension
    report = artifact_dir / 'rosa-gap-analysis-reports' / filename
    assert report_links.artifact_location(report) == (
        f'{ROOT_URL}/artifacts/nightly-5-0/5-0-gap-analysis/artifacts/rosa-gap-analysis-reports/{filename}'
    )


@pytest.mark.parametrize('raw', ['', '{', 'null', '[]', '123', '"string"'])
def test_malformed_metadata_is_local(ci_environment, monkeypatch, raw):
    _, artifact_dir = ci_environment
    monkeypatch.setenv('JOB_SPEC', raw)
    path = artifact_dir / REPORT
    assert report_links.artifact_location(path) == str(path)


@pytest.mark.parametrize('change', [
    {'type': 'presubmit'}, {'type': 'postsubmit'}, {'buildid': ''},
    {'buildid': '50a10731-d0bd-4a75-83ad-a7efcf049229'},
    {'decoration_config': {}}, {'job': '../job'},
    {'decoration_config': {'gcs_configuration': {'bucket': 'other', 'path_strategy': 'explicit'}}},
])
def test_unsupported_metadata_is_local(ci_environment, monkeypatch, change):
    spec, artifact_dir = ci_environment
    spec.update(change)
    monkeypatch.setenv('JOB_SPEC', json.dumps(spec))
    path = artifact_dir / REPORT
    assert report_links.artifact_location(path) == str(path)


@pytest.mark.parametrize('hostname', ['local-host', 'nightly-5-0-', 'nightly-5-0-invalid_step'])
def test_unknown_step_is_local(ci_environment, monkeypatch, hostname):
    _, artifact_dir = ci_environment
    monkeypatch.setattr(report_links.socket, 'gethostname', lambda: hostname)
    path = artifact_dir / REPORT
    assert report_links.artifact_location(path) == str(path)


@pytest.mark.parametrize('remote', [True, False])
def test_python_log_consumer(ci_environment, tmp_path, monkeypatch, remote):
    _, artifact_dir = ci_environment
    log_path = artifact_dir / 'rosa-gap-analysis-reports' / 'analysis log.txt'
    log_path.parent.mkdir()
    log_path.write_text('ERROR gate missing\n❌ FAILED\n')
    if not remote:
        monkeypatch.delenv('JOB_SPEC')
    metrics = generate_combined_report.parse_build_log(str(log_path))
    expected = f'{ROOT_URL}/artifacts/nightly-5-0/5-0-gap-analysis/artifacts/rosa-gap-analysis-reports/analysis%20log.txt'
    if not remote:
        expected = str(log_path)
    assert metrics['build_log_url'] == expected
    assert metrics['failures'][0]['log_url'] == expected
    assert metrics['status'] == 'FAILED'
    local_log = tmp_path / 'outside.log'
    local_log.write_text('ERROR local failure\n')
    assert generate_combined_report.parse_build_log(str(local_log))['build_log_url'] == str(local_log)
    assert 'build_log_url' not in generate_combined_report.parse_build_log(str(tmp_path / 'missing.log'))


@pytest.mark.parametrize('remote', [True, False])
@pytest.mark.parametrize('exit_code', [0, 1])
def test_actual_shell_summary(ci_environment, tmp_path, monkeypatch, remote, exit_code):
    _, artifact_dir = ci_environment
    checkout = tmp_path / 'checkout'
    shutil.copytree(ROOT / 'scripts', checkout / 'scripts')
    reports = artifact_dir / 'rosa-gap-analysis-reports'
    reports.mkdir()
    (reports / REPORT).write_text('report')
    (checkout / 'scripts' / 'gap-ocm-version-gate.py').write_text(
        'import json, os\nfrom pathlib import Path\n'
        f'Path(os.environ["REPORT_DIR"], "status-check-7.json").write_text(json.dumps('
        f'{{"status": "{ "FAIL" if exit_code else "PASS" }", "details": {{"message": "gate result"}}}}))\n'
        f'raise SystemExit({exit_code})\n'
    )
    startup = tmp_path / 'startup'
    startup.mkdir()
    (startup / 'sitecustomize.py').write_text(
        'import socket\nsocket.gethostname = lambda: "nightly-5-0-5-0-gap-analysis"\n'
    )
    monkeypatch.setenv('PYTHONPATH', str(startup))
    monkeypatch.setenv('REPORT_DIR', str(reports))
    log_path = reports / 'analysis.log'
    log_path.write_text('ERROR gate missing\n❌ FAILED\n')
    monkeypatch.setenv('BUILD_LOG', str(log_path))
    monkeypatch.setenv('job', 'job123')
    monkeypatch.setenv('buildid', 'build1234')
    if not remote:
        monkeypatch.delenv('JOB_SPEC')
    result = subprocess.run(
        ['bash', str(checkout / 'scripts' / 'gap-all.sh'), '--baseline', '4.22.20',
         '--target', '5.0.0-rc.8', '--steps', 'ocm-version-gate'],
        capture_output=True, text=True, env=os.environ.copy(),
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert f'OVERALL STATUS: {"FAILED" if exit_code else "SUCCESS"}' in result.stdout
    expected = (f'{ROOT_URL}/artifacts/nightly-5-0/5-0-gap-analysis/artifacts/rosa-gap-analysis-reports/{REPORT}'
                if remote else str(reports / REPORT))
    assert f'  • {expected}' in result.stdout
    assert 'job123' not in result.stdout
    assert 'build1234' not in result.stdout
    expected_log = (f'{ROOT_URL}/artifacts/nightly-5-0/5-0-gap-analysis/artifacts/rosa-gap-analysis-reports/analysis.log'
                    if remote else str(log_path))
    assert f'- Build log: {expected_log}' in result.stdout


def test_alternate_periodic_layout(ci_environment, monkeypatch):
    spec, artifact_dir = ci_environment
    spec['job'] = 'periodic-custom-nightly-4-22'
    spec['decoration_config']['gcs_configuration']['bucket'] = 'another-public-bucket'
    monkeypatch.setenv('JOB_SPEC', json.dumps(spec))
    monkeypatch.setenv('JOB_NAME_SAFE', 'nightly-4-22')
    monkeypatch.setattr(report_links.socket, 'gethostname', lambda: 'nightly-4-22-custom-step')
    assert report_links.artifact_location(artifact_dir / 'nested' / 'a b.html') == (
        f'https://storage.googleapis.com/another-public-bucket/logs/periodic-custom-nightly-4-22/{BUILD_ID}'
        '/artifacts/nightly-4-22/custom-step/artifacts/nested/a%20b.html'
    )


def test_underscore_test_name_is_not_guessed(ci_environment, monkeypatch):
    spec, artifact_dir = ci_environment
    spec['job'] = 'periodic-custom-nightly_5_0'
    monkeypatch.setenv('JOB_SPEC', json.dumps(spec))
    path = artifact_dir / REPORT
    assert report_links.artifact_location(path) == str(path)
