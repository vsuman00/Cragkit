"""Registry verification uses small fake responses, never live registry access."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import ssl
import signal
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_registry_products as R


class FakeHTTP:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url, **options):
        self.calls.append((url, options))
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def encoded(value):
    return json.dumps(value).encode()


@pytest.fixture
def registry(tmp_path, monkeypatch):
    summary = json.loads(R.SUMMARY.read_bytes())
    products, responses, raw_products = summary['products'], {}, {}
    for index, product in enumerate(products):
        raw = f'reviewed product {index}'.encode()
        product['bytes'] = len(raw)
        product['prepared_sha256'] = hashlib.sha256(raw).hexdigest()
        product['original_sha256'] = product['prepared_sha256']
        raw_products[product['path']] = raw
    for package in R.PACKAGES:
        group = [item for item in products if item['registry'] == 'pypi'
                 and item['package'] == package]
        files = []
        for item in group:
            name = Path(item['path']).name
            url = f'https://files.pythonhosted.org/packages/ab/cd/{"e" * 60}/{name}'
            files.append(dict(filename=name, size=item['bytes'], yanked=False,
                packagetype='bdist_wheel' if item['kind'] == 'wheel' else 'sdist',
                digests=dict(sha256=item['prepared_sha256']), url=url))
            responses[url] = (200, raw_products[item['path']])
        responses[f'https://pypi.org/pypi/{package}/1.0.0rc1/json'] = (200,
            encoded(dict(info=dict(name=package, version='1.0.0rc1'), urls=files)))
        item = next(item for item in products if item['registry'] == 'npm'
                    and item['package'] == package)
        raw = raw_products[item['path']]
        url = f'https://registry.npmjs.org/{package}/-/{package}-1.0.0-rc.1.tgz'
        responses[url] = (200, raw)
        responses[f'https://registry.npmjs.org/{package}/1.0.0-rc.1'] = (200,
            encoded(dict(name=package, version='1.0.0-rc.1', dist=dict(tarball=url,
                shasum=hashlib.sha1(raw).hexdigest(), integrity='sha512-' +
                    base64.b64encode(hashlib.sha512(raw).digest()).decode()))))
        responses[f'https://registry.npmjs.org/-/package/{package}/dist-tags'] = (
            200, encoded(dict(next='1.0.0-rc.1')))
    path = tmp_path / 'reviewed.json'
    path.write_bytes(encoded(summary))
    monkeypatch.setattr(R, 'SUMMARY', path)
    monkeypatch.setattr(R, 'SUMMARY_SHA256', hashlib.sha256(path.read_bytes()).hexdigest())
    http = FakeHTTP(responses)
    return products, responses, raw_products, http


def check(tmp_path, registry, **options):
    return R.check_registry(output=tmp_path / 'registry', transport=registry[3], **options)


def mutate_metadata(responses, registry, change):
    url = ('https://pypi.org/pypi/cragkit/1.0.0rc1/json' if registry == 'pypi'
           else 'https://registry.npmjs.org/cragkit/1.0.0-rc.1')
    data = json.loads(responses[url][1])
    change(data)
    responses[url] = 200, encoded(data)


def test_real_committed_reviewed_inventory_is_pinned_without_network():
    products = R.reviewed_products()
    assert len(products) == 9
    assert {item['registry'] for item in products} == {'pypi', 'npm'}
    assert R.MANIFEST_SHA256 == '7ced6f15ee096752d8e974d793d1bd99a8f41d77181fb061d2871d890aeb5dc5'


def test_complete_exact_bytes_receipt_and_eighteen_serial_bounded_gets(tmp_path, registry):
    report = check(tmp_path, registry)
    assert report['state'] == 'complete' and report['publication_complete'] is True
    assert report['request_count'] == len(registry[3].calls) == 18
    assert all(item['state'] == 'verified' for item in report['products'])
    assert all(item['state'] == 'match' for item in report['npm_next_tags'])
    output = tmp_path / 'registry'
    assert json.loads((output / R.REPORT).read_bytes()) == report
    for path, raw in registry[2].items():
        assert (output / path).read_bytes() == raw
        assert (output / path).stat().st_mode & 0o777 == 0o600
    assert len([path for path in output.rglob('*') if path.is_file()]) == 10
    for url, options in registry[3].calls:
        assert url.startswith('https://') and 0 < options['timeout'] <= 5
        assert options['limit'] <= R.MAX_METADATA


@pytest.mark.parametrize('allow_missing', [False, True])
def test_all_metadata_absent_is_partial_and_not_ownership_proof(tmp_path, registry, allow_missing):
    for url in registry[1]:
        if '/json' in url or '/1.0.0-rc.1' in url or '/dist-tags' in url:
            registry[1][url] = 404, b''
    report = check(tmp_path, registry, allow_missing=allow_missing)
    assert report['state'] == 'partial' and report['publication_complete'] is False
    assert report['request_count'] == 9
    assert all(item['state'] == 'absent' for item in report['products'])
    assert list((tmp_path / 'registry').iterdir()) == [tmp_path / 'registry' / R.REPORT]


def test_partial_python_publication_only_marks_missing_reviewed_file_absent(tmp_path, registry):
    mutate_metadata(registry[1], 'pypi', lambda data: data['urls'].pop())
    report = check(tmp_path, registry, allow_missing=True)
    assert report['state'] == 'partial'
    assert [item['state'] for item in report['products']].count('absent') == 1
    assert [item['state'] for item in report['products']].count('verified') == 8


@pytest.mark.parametrize('kind', ['pypi', 'npm'])
def test_claimed_file_404_is_error_and_not_publish_permission(tmp_path, registry, kind):
    url = next(url for url in registry[1] if (url.startswith('https://files.') if kind == 'pypi'
                   else url.endswith('.tgz')))
    registry[1][url] = 404, b''
    report = check(tmp_path, registry, allow_missing=True)
    assert report['state'] == 'failed'
    assert any(item.get('reason') == 'registry_file_missing' for item in report['products'])


@pytest.mark.parametrize('which', ['wrong_bytes', 'oversize', 'short'])
def test_file_bytes_and_size_drift_are_never_saved(tmp_path, registry, which):
    url = next(url for url in registry[1] if url.startswith('https://files.'))
    raw = registry[1][url][1]
    registry[1][url] = 200, raw + b'x' if which == 'oversize' else raw[:-1] if which == 'short' else b'x' * len(raw)
    report = check(tmp_path, registry)
    assert report['state'] == 'failed'
    failed = [item for item in report['products'] if item['state'] == 'error']
    assert len(failed) == 1 and not (tmp_path / 'registry' / failed[0]['path']).exists()


@pytest.mark.parametrize('change', ['name', 'version', 'digest', 'size', 'bool_size',
                                   'extra', 'duplicate', 'yanked', 'type', 'url'])
def test_pypi_metadata_contract_and_inventory(tmp_path, registry, change):
    def mutate(data):
        item = data['urls'][0]
        if change == 'name': data['info']['name'] = 'wrong'
        elif change == 'version': data['info']['version'] = '1.0'
        elif change == 'digest': item['digests']['sha256'] = '0' * 64
        elif change == 'size': item['size'] += 1
        elif change == 'bool_size': item['size'] = True
        elif change == 'extra': item['filename'] = 'unreviewed.whl'
        elif change == 'duplicate': data['urls'][1] = copy.deepcopy(item)
        elif change == 'yanked': item['yanked'] = True
        elif change == 'type': item['packagetype'] = 'sdist'
        elif change == 'url': item['url'] = item['url'].replace('files.pythonhosted.org', 'evil.example')
    mutate_metadata(registry[1], 'pypi', mutate)
    report = check(tmp_path, registry)
    assert report['state'] == 'failed'
    assert sum(item['state'] == 'error' for item in report['products']) == 2
    assert len(registry[3].calls) == 16


@pytest.mark.parametrize('change', ['name', 'version', 'tarball', 'integrity', 'shasum', 'no_digest'])
def test_npm_metadata_identity_url_and_available_digest_fields(tmp_path, registry, change):
    def mutate(data):
        if change in ('name', 'version'): data[change] = 'wrong'
        elif change == 'tarball': data['dist']['tarball'] += '?token=private-token'
        elif change == 'no_digest':
            data['dist'].pop('integrity')
            data['dist'].pop('shasum')
        else: data['dist'][change] = 'wrong'
    mutate_metadata(registry[1], 'npm', mutate)
    report = check(tmp_path, registry)
    assert report['state'] == 'failed'
    assert 'private-token' not in (tmp_path / 'registry' / R.REPORT).read_text()


@pytest.mark.parametrize('url', ['http://pypi.org/file', 'https://u:p@pypi.org/file',
    'https://pypi.org:443/file', 'https://pypi.org.evil/file', 'https://pypi.org/file?secret=x',
    'https://pypi.org/file#part', 'https://pypi.org/%2e/file', 'https://pypi.org/../file',
    'https://pypi.org/\\file', 'https://pypi.org/file\n', 'https://pypi.org/é'])
def test_unsafe_urls_rejected_before_transport(url):
    http = FakeHTTP({})
    with pytest.raises(R.RegistryError, match='unsafe_url'):
        R.Budget(http).get(url, 'pypi.org', 100)
    assert not http.calls


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
    b'{"a":1e999}', b'{"a":{"b":1,"b":2}}', b'[]', b'not-json', b'\xff'])
def test_strict_json_rejects_duplicates_nonfinite_and_invalid_shapes(raw):
    with pytest.raises(R.RegistryError):
        R.parse_json(raw)


@pytest.mark.parametrize('failure', [301, 302, 307, 308, 401, 403, 429, 500,
                                   ssl.SSLError('private-token'), TimeoutError('private-token')])
def test_http_tls_and_timeout_errors_cannot_be_absence(tmp_path, registry, failure):
    url = 'https://pypi.org/pypi/cragkit/1.0.0rc1/json'
    registry[1][url] = failure if isinstance(failure, Exception) else (failure, b'private-token')
    report = check(tmp_path, registry, allow_missing=True)
    assert report['state'] == 'failed'
    assert all(item['state'] == 'error' for item in report['products'][:2])
    assert 'private-token' not in (tmp_path / 'registry' / R.REPORT).read_text()
    assert sum(call[0] == url for call in registry[3].calls) == 1


@pytest.mark.parametrize('observed,state', [(None, 'absent'), ('0.9.0', 'different'),
                                           ('1.0.0-rc.1', 'match')])
def test_next_tag_is_observed_and_required_for_complete(tmp_path, registry, observed, state):
    url = 'https://registry.npmjs.org/-/package/cragkit/dist-tags'
    registry[1][url] = 200, encoded({} if observed is None else dict(next=observed))
    report = check(tmp_path, registry, allow_missing=True)
    assert report['npm_next_tags'][0]['state'] == state
    assert report['publication_complete'] is (state == 'match')


def test_next_tag_operational_failure_is_fatal_in_preflight(tmp_path, registry):
    registry[1]['https://registry.npmjs.org/-/package/cragkit/dist-tags'] = 403, b''
    report = check(tmp_path, registry, allow_missing=True)
    assert report['state'] == 'failed' and report['publication_complete'] is False


def test_request_count_is_bounded_and_does_not_retry():
    url = 'https://pypi.org/pypi/cragkit/1.0.0rc1/json'
    http = FakeHTTP({url: (200, b'{}')})
    budget = R.Budget(http)
    for _ in range(18):
        budget.get(url, 'pypi.org', 100)
    with pytest.raises(R.RegistryError, match='request_limit'):
        budget.get(url, 'pypi.org', 100)
    assert len(http.calls) == 18


def test_shared_deadline_rejects_before_start_and_request_deadline_after_response():
    current = [0.0]
    http = FakeHTTP({'https://pypi.org/x': (200, b'{}')})
    budget = R.Budget(http, lambda: current[0])
    current[0] = 60.0
    with pytest.raises(R.RegistryError, match='shared_deadline'):
        budget.get('https://pypi.org/x', 'pypi.org', 100)
    assert not http.calls
    current[0] = 0.0
    budget = R.Budget(http, lambda: current[0])
    original = http.get
    def late(*args, **kwargs):
        current[0] += 5.0
        return original(*args, **kwargs)
    http.get = late
    with pytest.raises(R.RegistryError, match='request_deadline'):
        budget.get('https://pypi.org/x', 'pypi.org', 100)


def test_metadata_size_is_bounded(tmp_path, registry):
    registry[1]['https://pypi.org/pypi/cragkit/1.0.0rc1/json'] = 200, b' ' * (R.MAX_METADATA + 1)
    report = check(tmp_path, registry)
    assert report['products'][0]['reason'] == 'response_size_limit'


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink', 'broken_symlink'])
def test_existing_output_preserved_before_any_network(tmp_path, registry, kind):
    output = tmp_path / 'registry'
    if kind == 'directory': output.mkdir()
    elif kind == 'file': output.write_bytes(b'foreign')
    else: output.symlink_to(tmp_path / ('reviewed.json' if kind == 'symlink' else 'missing'))
    with pytest.raises(R.RegistryError, match='output_exists'):
        check(tmp_path, registry)
    assert os.path.lexists(output) and registry[3].calls == []
    if kind == 'file': assert output.read_bytes() == b'foreign'


def test_replaced_expected_summary_is_rejected_without_network(tmp_path, registry):
    R.SUMMARY.write_bytes(R.SUMMARY.read_bytes() + b' ')
    with pytest.raises(R.RegistryError, match='reviewed_summary_digest'):
        check(tmp_path, registry)
    assert not registry[3].calls and not (tmp_path / 'registry').exists()


def test_claim_race_preserves_foreign_file(tmp_path, registry, monkeypatch):
    original = R.P.publish_directory
    output = tmp_path / 'registry'
    def race(*args, **kwargs):
        output.mkdir()
        (output / 'foreign').write_bytes(b'keep')
        return original(*args, **kwargs)
    monkeypatch.setattr(R.P, 'publish_directory', race)
    with pytest.raises(R.RegistryError):
        check(tmp_path, registry)
    assert (output / 'foreign').read_bytes() == b'keep'
    assert not list(tmp_path.glob('.cragkit-registry-*'))


@pytest.mark.parametrize('allow_missing,expected', [(False, 1), (True, 0)])
def test_cli_allow_missing_only_changes_partial_exit(monkeypatch, tmp_path, capsys, allow_missing, expected):
    monkeypatch.setattr(R, 'check_registry', lambda **kwargs: dict(state='partial', publication_complete=False))
    assert R.main(['--output', str(tmp_path / 'x')] + (['--allow-missing'] if allow_missing else [])) == expected
    assert json.loads(capsys.readouterr().out)['publication_complete'] is False


def test_cli_operational_failure_stays_nonzero_with_allow_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(R, 'check_registry', lambda **kwargs: dict(state='failed', publication_complete=False))
    assert R.main(['--output', str(tmp_path / 'x'), '--allow-missing']) == 1
    assert json.loads(capsys.readouterr().out)['state'] == 'failed'


def test_direct_https_ignores_proxy_auth_and_certificate_environment(monkeypatch):
    for name in ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NPM_TOKEN', 'PYPI_TOKEN',
                 'SSL_CERT_FILE', 'SSL_CERT_DIR'):
        monkeypatch.setenv(name, 'private-token')
    contexts, requests = [], []
    class Context:
        def __init__(self, protocol):
            assert protocol == ssl.PROTOCOL_TLS_CLIENT
        def load_verify_locations(self, **options):
            contexts.append(options)
    class Headers:
        def get_all(self, name):
            return ['2'] if name == 'Content-Length' else None
    class Response:
        status, headers = 200, Headers()
        def __init__(self): self.reads = 0
        def read1(self, limit):
            self.reads += 1
            return b'{}' if self.reads == 1 else b''
    class Connection:
        sock = None
        def __init__(self, host, **options):
            assert host == 'pypi.org' and options['timeout'] == 5
        def request(self, method, path, **options): requests.append((method, path, options))
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(R.ssl, 'SSLContext', Context)
    monkeypatch.setattr(R.http.client, 'HTTPSConnection', Connection)
    transport = R.PublicHTTPS(clock=lambda: 0.0)
    assert transport.get('https://pypi.org/x', limit=10, timeout=5, deadline=5) == (200, b'{}')
    assert contexts == [dict(cafile=ssl.get_default_verify_paths().openssl_cafile,
                             capath=ssl.get_default_verify_paths().openssl_capath)]
    assert requests[0][:2] == ('GET', '/x')
    headers = requests[0][2]['headers']
    assert 'Authorization' not in headers and 'Cookie' not in headers
    assert 'private-token' not in repr(requests + contexts)


@pytest.mark.parametrize('status,length,encoding,expected', [
    (302, None, None, 'http_status'), (401, None, None, 'http_status'),
    (200, ['100'], None, 'http_length'), (200, ['2', '2'], None, 'http_length'),
    (200, ['no'], None, 'http_length'), (200, None, ['gzip'], 'http_encoding')])
def test_https_rejects_redirects_status_and_headers_without_reading_body(
        monkeypatch, status, length, encoding, expected):
    class Headers:
        def get_all(self, name):
            return length if name == 'Content-Length' else encoding
    class Response:
        headers = Headers()
        def read1(self, limit): raise AssertionError('body must not be read')
    response = Response()
    response.status = status
    class Connection:
        sock = None
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(R.http.client, 'HTTPSConnection', Connection)
    transport = object.__new__(R.PublicHTTPS)
    transport.context, transport.clock = object(), lambda: 0.0
    with pytest.raises(R.RegistryError, match=expected):
        transport.get('https://pypi.org/x', limit=10, timeout=5, deadline=5)


@pytest.mark.parametrize('kind', ['success', 'absent', 'timeout', 'spawn_slow', 'error',
                                 'oversize', 'missing', 'malformed_absent'])
def test_supervised_request_is_bounded_reaped_and_private(monkeypatch, tmp_path, kind):
    current, children, directories = [0.0], [], []
    class Child:
        def __init__(self, command, **options):
            self.killed, self.waits, self.finished = False, [], False
            assert command[:4] == [sys.executable, '-E', '-s', '-B']
            assert options['env'] == {} and options['close_fds'] is True
            assert options['stdin'] == options['stdout'] == options['stderr'] == R.subprocess.DEVNULL
            output = Path(command[command.index('--worker-output') + 1])
            directories.append(output.parent)
            assert output.parent.stat().st_mode & 0o777 == 0o700
            if kind != 'missing':
                output.write_bytes(b'' if kind == 'absent' else b'x' * 11 if kind == 'oversize' else b'{}')
            if kind == 'spawn_slow': current[0] = 5.1
            children.append(self)
        def wait(self, timeout=None):
            self.waits.append(timeout)
            if timeout is not None and kind == 'timeout':
                raise R.subprocess.TimeoutExpired('redacted', timeout)
            self.finished = True
            return 4 if kind in ('absent', 'malformed_absent') else 1 if kind == 'error' else 0
        def poll(self): return 0 if self.finished else None
        def kill(self): self.killed = True
    monkeypatch.setattr(R.subprocess, 'Popen', Child)
    transport = R.SupervisedHTTPS(clock=lambda: current[0])
    if kind in ('success', 'absent'):
        assert transport.get('https://pypi.org/x', limit=10, timeout=5, deadline=5) == (
            (200, b'{}') if kind == 'success' else (404, b''))
    else:
        with pytest.raises(R.RegistryError) as error:
            transport.get('https://pypi.org/x', limit=10, timeout=5, deadline=5)
        assert str(error.value) in ('request_deadline', 'https_failed', 'worker_response')
    assert len(children) == 1 and children[0].finished
    if kind in ('timeout', 'spawn_slow'): assert children[0].killed
    assert children[0].waits[-1] is None
    assert all(not directory.exists() for directory in directories)


def test_supervisor_expired_deadline_never_spawns(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('must not spawn')
    monkeypatch.setattr(R.subprocess, 'Popen', forbidden)
    with pytest.raises(R.RegistryError, match='request_deadline'):
        R.SupervisedHTTPS(clock=lambda: 5.0).get('https://pypi.org/x', limit=10,
                                               timeout=5, deadline=5)


@pytest.mark.parametrize('status', [200, 404])
def test_internal_worker_writes_only_bounded_response_and_fixed_exit(tmp_path, monkeypatch, status):
    class Transport:
        def get(self, url, **options):
            assert url == 'https://pypi.org/x' and options['limit'] == 10
            return status, b'{}' if status == 200 else b''
    monkeypatch.setattr(R, 'PublicHTTPS', Transport)
    output = tmp_path / 'response.bin'
    assert R.http_worker(['--http-worker', 'https://pypi.org/x', '--worker-output', str(output),
                         '--worker-limit', '10', '--worker-timeout', '5']) == (0 if status == 200 else 4)
    assert output.read_bytes() == (b'{}' if status == 200 else b'')
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('url', ['http://pypi.org/x', 'https://evil.example/x',
                                'https://user:secret@pypi.org/x'])
def test_internal_worker_denies_unsafe_url_before_network(tmp_path, monkeypatch, url):
    def forbidden(*args, **kwargs): raise AssertionError('must not construct transport')
    monkeypatch.setattr(R, 'PublicHTTPS', forbidden)
    assert R.http_worker(['--http-worker', url, '--worker-output', str(tmp_path / 'out'),
                         '--worker-limit', '10', '--worker-timeout', '5']) == 1
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('algorithm', ['md5', 'blake2b_256', 'md5_digest'])
@pytest.mark.parametrize('valid', [False, True])
def test_available_pypi_digests_are_checked_against_actual_bytes(tmp_path, registry, algorithm, valid):
    product = next(item for item in registry[0] if item['registry'] == 'pypi'
                   and item['package'] == 'cragkit')
    raw = registry[2][product['path']]
    value = (hashlib.blake2b(raw, digest_size=32).hexdigest() if algorithm == 'blake2b_256'
             else hashlib.md5(raw).hexdigest()) if valid else '0' * 64
    def mutate(data):
        item = data['urls'][0]
        if algorithm == 'md5_digest': item[algorithm] = value
        else: item['digests'][algorithm] = value
    mutate_metadata(registry[1], 'pypi', mutate)
    report = check(tmp_path, registry)
    assert report['state'] == ('complete' if valid else 'failed')
    if not valid:
        assert report['products'][0]['reason'] == 'pypi_digest'
        assert not (tmp_path / 'registry' / product['path']).exists()


@pytest.mark.parametrize('value', ['unreviewed', ''])
def test_unknown_nonempty_pypi_digest_algorithm_is_rejected(tmp_path, registry, value):
    mutate_metadata(registry[1], 'pypi', lambda data: data['urls'][0]['digests'].update(future=value))
    report = check(tmp_path, registry)
    assert report['state'] == ('failed' if value else 'complete')


def test_cli_sigterm_interrupt_is_fixed_and_restores_previous_handler(tmp_path, monkeypatch, capsys):
    previous = signal.getsignal(signal.SIGTERM)
    def interrupt(**kwargs):
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not previous
        handler(signal.SIGTERM, None)
    monkeypatch.setattr(R, 'check_registry', interrupt)
    assert R.main(['--output', str(tmp_path / 'out')]) == 130
    assert json.loads(capsys.readouterr().out) == dict(revision='RPK-r1', state='failed',
                                                     reason='request_interrupted')
    assert signal.getsignal(signal.SIGTERM) is previous
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('mode', ['stalled', 'slow_progress'])
def test_real_nonnetwork_child_is_killed_reaped_and_cleaned_at_deadline(monkeypatch, mode):
    # Swap only the worker program for trusted local Python. No HTTP, DNS or
    # registry code runs in this regression; Popen/wait/kill are real OS calls.
    original = R.subprocess.Popen
    children, directories = [], []
    def spawn(command, **options):
        output = Path(command[command.index('--worker-output') + 1])
        directories.append(output.parent)
        program = ('import time; time.sleep(10)' if mode == 'stalled' else
            'import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\n'
            'with p.open("wb") as f:\n'
            ' for i in range(1000):\n  f.write(b"x"); f.flush(); time.sleep(0.01)\n')
        child = original([sys.executable, '-E', '-s', '-B', '-c', program, str(output)], **options)
        children.append(child)
        return child
    monkeypatch.setattr(R.subprocess, 'Popen', spawn)
    started = time.monotonic()
    try:
        with pytest.raises(R.RegistryError, match='request_deadline'):
            R.SupervisedHTTPS().get('https://pypi.org/x', limit=100,
                                   timeout=0.2, deadline=started + 0.2)
        assert time.monotonic() - started < 1.2
        assert len(children) == 1 and children[0].poll() is not None
        assert children[0].returncode < 0
        assert all(not directory.exists() for directory in directories)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
