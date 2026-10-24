import errno
import io
import json
import socket
import ssl
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError

import pytest

import common
import openshift_releases
from tests.conftest import _load_script_module


class Clock:
    def __init__(self):
        self.now = 0
        self.delays = []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(common.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(common.time, 'sleep', clock.sleep)
    return clock


def response_with(body):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = body
    return response


def dns_error(code=socket.EAI_NONAME):
    return URLError(socket.gaierror(code, 'Name or service not known'))


@pytest.mark.parametrize('code', [socket.EAI_NONAME, socket.EAI_AGAIN])
@pytest.mark.parametrize('wrapped', [True, False])
def test_dns_recovery(monkeypatch, clock, capsys, code, wrapped):
    error = dns_error(code)
    response = response_with(b'payload')
    opener = Mock(side_effect=[error if wrapped else error.reason, response])
    monkeypatch.setattr(common, 'urlopen', opener)
    assert common.fetch_url('https://example.test/path') == b'payload'
    assert opener.call_count == 2
    assert clock.delays == [5]
    response.__exit__.assert_called_once()
    logs = capsys.readouterr().err
    assert 'Fetch succeeded' in logs
    assert 'attempt=2/5' in logs


def test_attempt_exhaustion_preserves_original_error(monkeypatch, clock, capsys):
    error = dns_error()
    opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(URLError) as caught:
        common.fetch_url('https://example.test')
    assert caught.value is error
    assert opener.call_count == 5
    assert clock.delays == [5, 10, 20, 20]
    assert [call.kwargs['timeout'] for call in opener.call_args_list] == [30, 30, 30, 25, 5]
    logs = capsys.readouterr().err
    assert 'attempt=5/5 elapsed=55.000s budget=60s' in logs
    assert 'EAI_NONAME' in logs


def test_request_time_counts_toward_budget(monkeypatch, clock):
    error = dns_error()

    def fail(*args, **kwargs):
        clock.now += 28
        raise error

    opener = Mock(side_effect=fail)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(URLError) as caught:
        common.fetch_url('https://example.test')
    assert caught.value is error
    assert opener.call_count == 2
    assert clock.delays == [5]
    assert opener.call_args.kwargs['timeout'] == 27


def test_sleep_overshoot_starts_no_new_attempt(monkeypatch, clock, capsys):
    error = dns_error()
    opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    monkeypatch.setattr(common.time, 'sleep', lambda delay: setattr(clock, 'now', 61))
    with pytest.raises(URLError) as caught:
        common.fetch_url('https://example.test')
    assert caught.value is error
    assert opener.call_count == 1
    assert 'completed_attempts=1' in capsys.readouterr().err


def test_budget_expires_before_first_attempt(monkeypatch, clock):
    monkeypatch.setattr(common.time, 'monotonic', Mock(side_effect=[0, 61]))
    opener = Mock()
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(TimeoutError, match='before first attempt'):
        common.fetch_url('https://example.test')
    opener.assert_not_called()
    assert clock.delays == []


def test_success_elapsed_includes_request_time(monkeypatch, clock, capsys):
    def read():
        clock.now += 3
        return b'ok'

    response = response_with(b'ignored')
    response.__enter__.return_value.read.side_effect = read
    monkeypatch.setattr(common, 'urlopen', Mock(side_effect=[dns_error(), response]))
    assert common.fetch_url('https://example.test') == b'ok'
    assert "Fetch succeeded: endpoint='example.test' attempt=2/5 elapsed=8.000s" in capsys.readouterr().err


@pytest.mark.parametrize('error', [
    URLError(ssl.SSLCertVerificationError('certificate secret')),
    ssl.SSLError('TLS secret'),
    URLError('unclassified failure secret'),
    URLError(socket.gaierror(socket.EAI_FAIL, 'resolver secret')),
])
def test_permanent_transport_errors_fail_fast(monkeypatch, clock, error):
    opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises((URLError, OSError)) as caught:
        common.fetch_url('https://example.test')
    assert caught.value is error
    assert opener.call_count == 1
    assert clock.delays == []


@pytest.mark.parametrize('status', [400, 401, 403, 404, 408, 429, 500, 502, 503, 504])
def test_http_classification_and_cleanup(monkeypatch, clock, capsys, status):
    body = io.BytesIO(b'private response body')
    error = HTTPError('https://example.test/?secret=value', status, 'secret reason', {}, body)
    opener = Mock(side_effect=[error, response_with(b'ok')])
    monkeypatch.setattr(common, 'urlopen', opener)
    if status in {408, 429, 502, 503, 504}:
        assert common.fetch_url('https://example.test') == b'ok'
        assert opener.call_count == 2
        assert clock.delays == [5]
    else:
        with pytest.raises(HTTPError) as caught:
            common.fetch_url('https://example.test')
        assert caught.value is error
        assert opener.call_count == 1
        assert clock.delays == []
    assert body.closed
    logs = capsys.readouterr().err
    assert f'HTTPError status={status}' in logs
    for forbidden in ('private response body', 'secret=value', 'secret reason'):
        assert forbidden not in logs


@pytest.mark.parametrize('error', [TimeoutError(), ConnectionResetError(errno.ECONNRESET, 'reset')])
def test_read_failure_closes_response_before_retry(monkeypatch, clock, error):
    failed = response_with(b'ignored')
    failed.__enter__.return_value.read.side_effect = error
    good = response_with(b'ok')
    monkeypatch.setattr(common, 'urlopen', Mock(side_effect=[failed, good]))
    assert common.fetch_url('https://example.test') == b'ok'
    failed.__exit__.assert_called_once()
    good.__exit__.assert_called_once()
    assert clock.delays == [5]


def test_safe_diagnostics(monkeypatch, clock, capsys):
    reason = socket.gaierror(socket.EAI_NONAME, 'resolver=192.0.2.53 secret-message\nINJECT')
    monkeypatch.setattr(common, 'urlopen', Mock(side_effect=URLError(reason)))
    with pytest.raises(URLError):
        common.fetch_url('https://username:password@example.test/private-token?access_token=query-secret#fragment-secret')
    logs = capsys.readouterr().err
    for forbidden in ('username', 'password', 'private-token', 'query-secret', 'fragment-secret',
                      '192.0.2.53', 'secret-message', 'INJECT'):
        assert forbidden not in logs
    for required in ("endpoint='example.test'", 'attempt=1/5', 'elapsed=0.000s', 'budget=60s',
                     'gaierror', 'EAI_NONAME'):
        assert required in logs


@pytest.mark.parametrize('wrapper', ['fetch_accepted_streams', 'fetch_sippy_ga_dates', 'get_latest_dev_nightly_version'])
def test_release_wrappers_preserve_exit_one(monkeypatch, clock, capsys, wrapper):
    monkeypatch.setattr(openshift_releases, 'get_latest_ga_version', lambda: '4.21')
    opener = Mock(side_effect=dns_error())
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(SystemExit) as caught:
        getattr(openshift_releases, wrapper)()
    assert caught.value.code == 1
    assert opener.call_count == 5
    assert 'attempt=5/5' in capsys.readouterr().err


def test_invalid_json_is_not_retried_or_logged(monkeypatch, clock, capsys):
    response = response_with(b'{"private body secret": invalid}')
    opener = Mock(return_value=response)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(SystemExit) as caught:
        openshift_releases.fetch_accepted_streams()
    assert caught.value.code == 1
    assert opener.call_count == 1
    assert clock.delays == []
    response.__exit__.assert_called_once()
    logs = capsys.readouterr().err
    assert 'JSONDecodeError line=1 column=' in logs
    assert 'private body secret' not in logs


@pytest.mark.parametrize('recover', [True, False])
def test_check13_real_entrypoint_before_upgrade_evaluation(monkeypatch, clock, tmp_path, capsys, recover):
    script = _load_script_module('gap_upgrade_e2e_http_test', 'gap-upgrade-e2e.py')
    monkeypatch.setenv('OPENSHIFT_VERSION', '4.21')
    monkeypatch.setattr('sys.argv', [
        'gap-upgrade-e2e.py', '--baseline', '4.21.38', '--target', '4.21.39',
        '--report-dir', str(tmp_path), '--dry-run',
    ])
    body = json.dumps({'4-stable': ['4.21.39', '4.21.38']}).encode()
    accepted = (Mock(side_effect=[dns_error(), response_with(body), response_with(body), response_with(body)])
                if recover else Mock(side_effect=dns_error()))

    def route(request, **kwargs):
        if request.full_url == openshift_releases.SIPPY_API:
            return response_with(b'{"ga_dates":{"4.21":"2026-09-01"}}')
        return accepted(request, **kwargs)

    opener = Mock(side_effect=route)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(SystemExit) as caught:
        script.main()
    assert caught.value.code == (0 if recover else 1)
    assert accepted.call_count == (4 if recover else 5)
    assert opener.call_args.args[0].full_url == openshift_releases.ACCEPTED_STREAMS_API
    logs = capsys.readouterr().err
    if recover:
        assert 'Dry-run mode enabled' in logs
    else:
        assert 'Failed to fetch accepted release streams' in logs
        assert "endpoint='amd64.ocp.releases.ci.openshift.org' attempt=5/5" in logs
        assert not list(tmp_path.iterdir())
