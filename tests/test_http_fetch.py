import errno
import io
import socket
import ssl
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError

import pytest

import common
import openshift_releases
import prow_artifacts


class Clock:
    def __init__(self):
        self.elapsed = 0
        self.delays = []

    def monotonic(self):
        return self.elapsed

    def sleep(self, delay):
        self.delays.append(delay)
        self.elapsed += delay


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(common, 'time', clock)
    return clock


def response_with(body):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = body
    return response


def dns_error(code=socket.EAI_NONAME):
    return URLError(socket.gaierror(code, 'DNS lookup failed'))


def http_error(status):
    return HTTPError('https://example.test/data', status, 'request failed', {}, io.BytesIO(b'error'))


def test_success_preserves_request_headers_and_timeout(monkeypatch, clock):
    opener = Mock(return_value=response_with(b'payload'))
    monkeypatch.setattr(common, 'urlopen', opener)
    assert common.fetch_url('https://example.test/data', timeout=10) == b'payload'
    request = opener.call_args.args[0]
    assert request.full_url == 'https://example.test/data'
    assert request.get_header('User-agent') == 'gap-analysis-script'
    assert opener.call_args.kwargs['timeout'] == 10
    assert opener.call_count == 1
    assert clock.delays == []


@pytest.mark.parametrize('code', [socket.EAI_NONAME, socket.EAI_AGAIN])
def test_dns_recovery_has_time_to_recover(monkeypatch, clock, code):
    opener = Mock(side_effect=[dns_error(code) for _ in range(4)] + [response_with(b'recovered')])
    monkeypatch.setattr(common, 'urlopen', opener)
    assert common.fetch_url('https://example.test/data', timeout=10) == b'recovered'
    assert opener.call_count == 5
    assert clock.delays == [5, 10, 20, 20]
    assert clock.elapsed == 55
    assert [call.kwargs['timeout'] for call in opener.call_args_list] == [10, 10, 10, 10, 5]


def test_dns_exhaustion_raises_original_error(monkeypatch, clock):
    error = dns_error()
    opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(URLError) as caught:
        common.fetch_url('https://example.test/data')
    assert caught.value is error
    assert opener.call_count == 5
    assert clock.delays == [5, 10, 20, 20]


def test_retry_budget_includes_request_time(monkeypatch, clock):
    error = dns_error()

    def slow_failure(*args, **kwargs):
        clock.elapsed += kwargs['timeout']
        raise error

    opener = Mock(side_effect=slow_failure)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(URLError) as caught:
        common.fetch_url('https://example.test/data', timeout=45)
    assert caught.value is error
    assert opener.call_count == 2
    assert clock.elapsed == 60
    assert [call.kwargs['timeout'] for call in opener.call_args_list] == [45, 10]
    assert clock.delays == [5]


def test_oversleep_does_not_start_request_after_deadline(monkeypatch, clock):
    error = dns_error()
    opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    monkeypatch.setattr(clock, 'sleep', lambda delay: setattr(clock, 'elapsed', 60))
    with pytest.raises(URLError) as caught:
        common.fetch_url('https://example.test/data')
    assert caught.value is error
    assert opener.call_count == 1


@pytest.mark.parametrize('status', [408, 429, 502, 503, 504])
def test_transient_http_recovers_and_closes_error(monkeypatch, clock, status):
    error = http_error(status)
    opener = Mock(side_effect=[error, response_with(b'recovered')])
    monkeypatch.setattr(common, 'urlopen', opener)
    assert common.fetch_url('https://example.test/data') == b'recovered'
    assert error.fp.closed
    assert opener.call_count == 2
    assert clock.delays == [5]


@pytest.mark.parametrize('status', [400, 401, 403, 404, 409, 422, 500, 501, 505])
def test_permanent_http_fails_fast(monkeypatch, clock, status):
    error = http_error(status)
    opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(HTTPError) as caught:
        common.fetch_url('https://example.test/data')
    assert caught.value is error
    assert not error.fp.closed
    assert opener.call_count == 1
    assert clock.delays == []


@pytest.mark.parametrize('error', [
    TimeoutError('timed out'),
    ConnectionResetError(errno.ECONNRESET, 'reset'),
    URLError(TimeoutError('timed out')),
    URLError(ConnectionRefusedError(errno.ECONNREFUSED, 'refused')),
])
def test_transient_transport_recovers(monkeypatch, clock, error):
    opener = Mock(side_effect=[error, response_with(b'recovered')])
    monkeypatch.setattr(common, 'urlopen', opener)
    assert common.fetch_url('https://example.test/data') == b'recovered'
    assert opener.call_count == 2
    assert clock.delays == [5]


@pytest.mark.parametrize('error', [
    URLError(socket.gaierror(socket.EAI_FAIL, 'permanent DNS failure')),
    URLError(ssl.SSLCertVerificationError('invalid certificate')),
    URLError('unsupported URL'),
    OSError(errno.EACCES, 'permission denied'),
    ValueError('invalid URL'),
])
def test_permanent_transport_or_application_error_fails_fast(monkeypatch, clock, error):
    opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(type(error)) as caught:
        common.fetch_url('https://example.test/data')
    assert caught.value is error
    assert opener.call_count == 1
    assert clock.delays == []


def test_response_read_timeout_recovers(monkeypatch, clock):
    response = response_with(b'ignored')
    response.__enter__.return_value.read.side_effect = TimeoutError('read timed out')
    opener = Mock(side_effect=[response, response_with(b'recovered')])
    monkeypatch.setattr(common, 'urlopen', opener)
    assert common.fetch_url('https://example.test/data') == b'recovered'
    assert response.__exit__.called
    assert opener.call_count == 2
    assert clock.delays == [5]


@pytest.mark.parametrize('wrapper,body,expected,url', [
    ('fetch_sippy_ga_dates', b'{"ga_dates":{"4.21":"2026-09-01"}}', {'4.21': '2026-09-01'},
     openshift_releases.SIPPY_API),
    ('fetch_accepted_streams', b'{"4-stable":["4.21.1"]}', {'4-stable': ['4.21.1']},
     openshift_releases.ACCEPTED_STREAMS_API),
    ('get_latest_dev_nightly_version', b'{"name":"4.22.0-0.nightly"}', '4.22.0-0.nightly',
     openshift_releases.RELEASE_STREAM_BASE + '/4.22.0-0.nightly/latest?rel=1'),
])
def test_release_wrappers_use_shared_retries(monkeypatch, clock, wrapper, body, expected, url):
    monkeypatch.setattr(openshift_releases, 'get_latest_ga_version', lambda: '4.21')
    opener = Mock(side_effect=[dns_error(), response_with(body)])
    monkeypatch.setattr(common, 'urlopen', opener)
    assert getattr(openshift_releases, wrapper)() == expected
    assert opener.call_args.args[0].full_url == url
    assert all(call.kwargs['timeout'] == 10 for call in opener.call_args_list)
    assert opener.call_count == 2
    assert clock.delays == [5]


@pytest.mark.parametrize('wrapper', ['fetch_sippy_ga_dates', 'fetch_accepted_streams', 'get_latest_dev_nightly_version'])
@pytest.mark.parametrize('failure', ['dns', 'timeout', 'http', 'json'])
def test_release_wrappers_preserve_terminal_failure(monkeypatch, clock, wrapper, failure):
    monkeypatch.setattr(openshift_releases, 'get_latest_ga_version', lambda: '4.21')
    if failure == 'json':
        opener = Mock(return_value=response_with(b'not json'))
    else:
        error = {'dns': dns_error(), 'timeout': TimeoutError('timed out'), 'http': http_error(403)}[failure]
        opener = Mock(side_effect=error)
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(SystemExit) as caught:
        getattr(openshift_releases, wrapper)()
    assert caught.value.code == 1
    assert opener.call_count == (5 if failure in ('dns', 'timeout') else 1)
    assert clock.delays == ([5, 10, 20, 20] if failure in ('dns', 'timeout') else [])


def test_missing_nightly_name_is_not_retried(monkeypatch, clock):
    monkeypatch.setattr(openshift_releases, 'get_latest_ga_version', lambda: '4.21')
    opener = Mock(return_value=response_with(b'{}'))
    monkeypatch.setattr(common, 'urlopen', opener)
    with pytest.raises(SystemExit) as caught:
        openshift_releases.get_latest_dev_nightly_version()
    assert caught.value.code == 1
    assert opener.call_count == 1
    assert clock.delays == []


def test_api_snapshot_selection_retries_sippy_dns(monkeypatch, clock):
    monkeypatch.setattr(prow_artifacts, '_GA_DATES_CACHE', None)
    opener = Mock(side_effect=[dns_error(), response_with(b'{"ga_dates":{"4.21":"2026-09-01"}}')])
    monkeypatch.setattr(common, 'urlopen', opener)
    assert prow_artifacts.snapshot_channels('4.22') == list(prow_artifacts.PRE_GA_SNAPSHOT_CHANNELS)
    assert opener.call_count == 2
    assert clock.delays == [5]


@pytest.mark.parametrize('fetcher', ['fetch_json_url', 'fetch_text_url'])
def test_artifact_404_still_falls_back_without_retry(monkeypatch, clock, fetcher):
    body = b'{"ok":true}' if fetcher == 'fetch_json_url' else b'payload'
    expected = {'ok': True} if fetcher == 'fetch_json_url' else 'payload'
    opener = Mock(side_effect=[http_error(404), response_with(body)])
    monkeypatch.setattr(common, 'urlopen', opener)
    payload, url = prow_artifacts._load_artifact('job', '1', 'test', 'artifact', 'step',
                                               getattr(prow_artifacts, fetcher))
    assert payload == expected
    assert url.startswith(prow_artifacts.ARTIFACT_HTTP_BASES[1])
    assert opener.call_count == 2
    assert clock.delays == []


def test_artifact_json_error_is_not_retried(monkeypatch, clock):
    opener = Mock(return_value=response_with(b'{invalid json'))
    monkeypatch.setattr(common, 'urlopen', opener)
    assert prow_artifacts.fetch_json_url('https://example.test/data') is None
    assert opener.call_count == 1
    assert clock.delays == []
